"""Topological fraud pattern detectors for MuleChain engine."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import networkx as nx

from sentinel_chain_drive.db.models.alert import (
    AlertSeverity,
    DetectorType,
)
from sentinel_chain_drive.services.mulechain.fingerprint import compute_alert_fingerprint
from sentinel_chain_drive.services.mulechain.models import (
    CircularLayeringConfig,
    DetectorFinding,
    FanInConfig,
    FanOutConfig,
    RapidPassThroughConfig,
    TransactionEdgeData,
)


class BaseDetector:
    """Base class for topological graph pattern detectors."""

    def __init__(self, currency: str) -> None:
        self.currency = currency.upper()

    def detect(self, graph: nx.MultiDiGraph) -> list[DetectorFinding]:  # type: ignore[type-arg]
        raise NotImplementedError


class FanInDetector(BaseDetector):
    """Detects multiple distinct source accounts transferring funds into a common destination."""

    def __init__(self, currency: str, config: FanInConfig | None = None) -> None:
        super().__init__(currency)
        self.config = config or FanInConfig()

    def detect(self, graph: nx.MultiDiGraph) -> list[DetectorFinding]:  # type: ignore[type-arg]
        findings: list[DetectorFinding] = []
        window_seconds = self.config.window_seconds
        min_sources = self.config.min_sources

        for dst_node in graph.nodes():
            # Inbound edges to dst_node
            in_edges = graph.in_edges(dst_node, keys=True, data=True)
            if not in_edges:
                continue

            # Filter out self-transfers and extract edge data
            valid_edges: list[TransactionEdgeData] = []
            for u, v, _k, data in in_edges:
                if u == v:
                    continue
                edge_data: TransactionEdgeData = data["data"]
                valid_edges.append(edge_data)

            if len(valid_edges) < min_sources:
                continue

            # Sort inbound edges chronologically
            valid_edges.sort(key=lambda e: e.timestamp)

            # Slide window over inbound edges
            n = len(valid_edges)
            seen_source_groups: list[set[uuid.UUID]] = []

            for i in range(n):
                window_start = valid_edges[i].timestamp
                window_end_limit = window_start + timedelta(seconds=window_seconds)

                window_edges: list[TransactionEdgeData] = []
                distinct_sources: set[uuid.UUID] = set()

                for j in range(i, n):
                    edge = valid_edges[j]
                    if edge.timestamp > window_end_limit:
                        break
                    window_edges.append(edge)
                    distinct_sources.add(edge.source_account_id)

                if len(distinct_sources) >= min_sources:
                    if any(distinct_sources.issubset(seen) for seen in seen_source_groups):
                        continue
                    seen_source_groups.append(set(distinct_sources))

                    # Compute metrics
                    total_amount = sum((e.amount for e in window_edges), Decimal("0"))
                    tx_ids = [e.transaction_id for e in window_edges]
                    source_ids = list(distinct_sources)
                    all_account_ids = [dst_node, *source_ids]

                    node_attrs = graph.nodes[dst_node]
                    institution_id = (
                        node_attrs.get("institution_id")
                        or window_edges[0].destination_institution_id
                    )

                    # Scoring logic: Base 65 for fan-in smurfing ingress + source volume modifier
                    volume_bonus = min(20, (len(distinct_sources) - min_sources) * 2)
                    raw_score = min(100, 65 + volume_bonus)
                    severity = (
                        AlertSeverity.CRITICAL
                        if raw_score >= 85
                        else AlertSeverity.HIGH
                        if raw_score >= 60
                        else AlertSeverity.MEDIUM
                    )

                    evidence = {
                        "detector": DetectorType.FAN_IN.value,
                        "destination_account_id": str(dst_node),
                        "source_count": len(distinct_sources),
                        "min_sources_threshold": min_sources,
                        "aggregate_amount": str(total_amount),
                        "currency": self.currency,
                        "window_seconds": window_seconds,
                        "window_start": window_edges[0].timestamp.isoformat(),
                        "window_end": window_edges[-1].timestamp.isoformat(),
                        "source_account_ids": [str(s) for s in source_ids],
                        "transaction_ids": [str(t) for t in tx_ids],
                        "score_breakdown": {
                            "base_score": 65,
                            "volume_bonus": volume_bonus,
                            "final_score": raw_score,
                        },
                        "pattern_description": (
                            f"Smurfing Ingress: {len(distinct_sources)} distinct source accounts "
                            f"transferred {total_amount} {self.currency} into destination account "
                            f"within {window_seconds}s window."
                        ),
                    }

                    fingerprint = compute_alert_fingerprint(
                        institution_id=institution_id,
                        detector_type=DetectorType.FAN_IN,
                        primary_account_id=dst_node,
                        currency=self.currency,
                        involved_transaction_ids=tx_ids,
                        rule_version=self.config.rule_version,
                    )

                    findings.append(
                        DetectorFinding(
                            detector_type=DetectorType.FAN_IN,
                            alert_code="MULE_FAN_IN",
                            primary_account_id=dst_node,
                            primary_institution_id=institution_id,
                            currency=self.currency,
                            analysis_window_start=window_edges[0].timestamp,
                            analysis_window_end=window_edges[-1].timestamp,
                            detection_rule_version=self.config.rule_version,
                            scoring_model_version="v1.0",
                            risk_score=raw_score,
                            severity=severity,
                            evidence_data=evidence,
                            involved_account_ids=all_account_ids,
                            involved_transaction_ids=tx_ids,
                            dedup_fingerprint=fingerprint,
                        )
                    )

        return findings


class FanOutDetector(BaseDetector):
    """Detects a single source account distributing funds to multiple distinct
    destination accounts.
    """

    def __init__(self, currency: str, config: FanOutConfig | None = None) -> None:
        super().__init__(currency)
        self.config = config or FanOutConfig()

    def detect(self, graph: nx.MultiDiGraph) -> list[DetectorFinding]:  # type: ignore[type-arg]
        findings: list[DetectorFinding] = []
        window_seconds = self.config.window_seconds
        min_destinations = self.config.min_destinations

        for src_node in graph.nodes():
            out_edges = graph.out_edges(src_node, keys=True, data=True)
            if not out_edges:
                continue

            valid_edges: list[TransactionEdgeData] = []
            for u, v, _k, data in out_edges:
                if u == v:
                    continue
                edge_data: TransactionEdgeData = data["data"]
                valid_edges.append(edge_data)

            if len(valid_edges) < min_destinations:
                continue

            valid_edges.sort(key=lambda e: e.timestamp)
            n = len(valid_edges)
            seen_dest_groups: list[set[uuid.UUID]] = []

            for i in range(n):
                window_start = valid_edges[i].timestamp
                window_end_limit = window_start + timedelta(seconds=window_seconds)

                window_edges: list[TransactionEdgeData] = []
                distinct_dests: set[uuid.UUID] = set()

                for j in range(i, n):
                    edge = valid_edges[j]
                    if edge.timestamp > window_end_limit:
                        break
                    window_edges.append(edge)
                    distinct_dests.add(edge.destination_account_id)

                if len(distinct_dests) >= min_destinations:
                    if any(distinct_dests.issubset(seen) for seen in seen_dest_groups):
                        continue
                    seen_dest_groups.append(set(distinct_dests))

                    total_amount = sum((e.amount for e in window_edges), Decimal("0"))
                    tx_ids = [e.transaction_id for e in window_edges]
                    dest_ids = list(distinct_dests)
                    all_account_ids = [src_node, *dest_ids]

                    node_attrs = graph.nodes[src_node]
                    institution_id = (
                        node_attrs.get("institution_id") or window_edges[0].source_institution_id
                    )

                    # Scoring: Base 60 for fan-out rapid dispersal + volume bonus
                    volume_bonus = min(20, (len(distinct_dests) - min_destinations) * 2)
                    raw_score = min(100, 60 + volume_bonus)
                    severity = (
                        AlertSeverity.CRITICAL
                        if raw_score >= 85
                        else AlertSeverity.HIGH
                        if raw_score >= 60
                        else AlertSeverity.MEDIUM
                    )

                    evidence = {
                        "detector": DetectorType.FAN_OUT.value,
                        "source_account_id": str(src_node),
                        "destination_count": len(distinct_dests),
                        "min_destinations_threshold": min_destinations,
                        "aggregate_amount": str(total_amount),
                        "currency": self.currency,
                        "window_seconds": window_seconds,
                        "window_start": window_edges[0].timestamp.isoformat(),
                        "window_end": window_edges[-1].timestamp.isoformat(),
                        "destination_account_ids": [str(d) for d in dest_ids],
                        "transaction_ids": [str(t) for t in tx_ids],
                        "score_breakdown": {
                            "base_score": 60,
                            "volume_bonus": volume_bonus,
                            "final_score": raw_score,
                        },
                        "pattern_description": (
                            f"Rapid Dispersal: Source distributed {total_amount} {self.currency} "
                            f"across {len(distinct_dests)} destinations in {window_seconds}s."
                        ),
                    }

                    fingerprint = compute_alert_fingerprint(
                        institution_id=institution_id,
                        detector_type=DetectorType.FAN_OUT,
                        primary_account_id=src_node,
                        currency=self.currency,
                        involved_transaction_ids=tx_ids,
                        rule_version=self.config.rule_version,
                    )

                    findings.append(
                        DetectorFinding(
                            detector_type=DetectorType.FAN_OUT,
                            alert_code="MULE_FAN_OUT",
                            primary_account_id=src_node,
                            primary_institution_id=institution_id,
                            currency=self.currency,
                            analysis_window_start=window_edges[0].timestamp,
                            analysis_window_end=window_edges[-1].timestamp,
                            detection_rule_version=self.config.rule_version,
                            scoring_model_version="v1.0",
                            risk_score=raw_score,
                            severity=severity,
                            evidence_data=evidence,
                            involved_account_ids=all_account_ids,
                            involved_transaction_ids=tx_ids,
                            dedup_fingerprint=fingerprint,
                        )
                    )

        return findings


class RapidPassThroughDetector(BaseDetector):
    """Detects transit mule behavior: funds entering and rapidly exiting with
    high retention ratio.
    """

    def __init__(self, currency: str, config: RapidPassThroughConfig | None = None) -> None:
        super().__init__(currency)
        self.config = config or RapidPassThroughConfig()

    def detect(self, graph: nx.MultiDiGraph) -> list[DetectorFinding]:  # type: ignore[type-arg]
        findings: list[DetectorFinding] = []
        max_delta_seconds = self.config.max_delta_seconds
        min_ratio = Decimal(str(self.config.min_pass_through_ratio))

        for node in graph.nodes():
            in_edges = graph.in_edges(node, keys=True, data=True)
            out_edges = graph.out_edges(node, keys=True, data=True)
            if not in_edges or not out_edges:
                continue

            # Extract ingress transactions (excluding self-transfers)
            ingress_list: list[TransactionEdgeData] = []
            for u, v, _key, d in in_edges:
                if u == v:
                    continue
                ingress_list.append(d["data"])

            egress_list: list[TransactionEdgeData] = []
            for u, v, _key, d in out_edges:
                if u == v:
                    continue
                egress_list.append(d["data"])

            if not ingress_list or not egress_list:
                continue

            # Sort egress by timestamp
            egress_list.sort(key=lambda e: e.timestamp)

            seen_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()

            for in_tx in ingress_list:
                for out_tx in egress_list:
                    # Ingress must precede egress
                    delta_seconds = (out_tx.timestamp - in_tx.timestamp).total_seconds()
                    if delta_seconds <= 0:
                        continue
                    if delta_seconds > max_delta_seconds:
                        continue

                    # Source and final destination cannot be the mule account itself
                    if in_tx.source_account_id == out_tx.destination_account_id:
                        # Direct refund/ping-pong is handled by circular flow or separate rule
                        continue

                    if in_tx.amount <= Decimal("0"):
                        continue

                    pass_through_ratio = out_tx.amount / in_tx.amount
                    if pass_through_ratio < min_ratio:
                        continue

                    pair_key = (in_tx.transaction_id, out_tx.transaction_id)
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)

                    node_attrs = graph.nodes[node]
                    institution_id = (
                        node_attrs.get("institution_id")
                        or in_tx.destination_institution_id
                    )

                    # Scoring: Base 75 for rapid transit mule
                    # Velocity bonus: faster pass-through (< 5 mins = 300s) adds risk points
                    speed_bonus = 10 if delta_seconds <= 300 else 5 if delta_seconds <= 900 else 0
                    raw_score = min(100, 75 + speed_bonus)
                    severity = AlertSeverity.CRITICAL if raw_score >= 85 else AlertSeverity.HIGH

                    tx_ids = [in_tx.transaction_id, out_tx.transaction_id]
                    involved_accounts = [
                        node,
                        in_tx.source_account_id,
                        out_tx.destination_account_id,
                    ]

                    evidence = {
                        "detector": DetectorType.RAPID_PASSTHROUGH.value,
                        "mule_account_id": str(node),
                        "source_account_id": str(in_tx.source_account_id),
                        "destination_account_id": str(out_tx.destination_account_id),
                        "ingress_transaction_id": str(in_tx.transaction_id),
                        "egress_transaction_id": str(out_tx.transaction_id),
                        "ingress_amount": str(in_tx.amount),
                        "egress_amount": str(out_tx.amount),
                        "pass_through_ratio": float(pass_through_ratio),
                        "min_ratio_threshold": float(min_ratio),
                        "delta_seconds": delta_seconds,
                        "max_delta_seconds": max_delta_seconds,
                        "currency": self.currency,
                        "disclaimer": (
                            "Suspicious flow pattern: ingress immediately followed by "
                            "proportional egress within configured time tolerance without "
                            "asserting serial coin traceability."
                        ),
                        "score_breakdown": {
                            "base_score": 75,
                            "speed_bonus": speed_bonus,
                            "final_score": raw_score,
                        },
                    }

                    fingerprint = compute_alert_fingerprint(
                        institution_id=institution_id,
                        detector_type=DetectorType.RAPID_PASSTHROUGH,
                        primary_account_id=node,
                        currency=self.currency,
                        involved_transaction_ids=tx_ids,
                        rule_version=self.config.rule_version,
                    )

                    findings.append(
                        DetectorFinding(
                            detector_type=DetectorType.RAPID_PASSTHROUGH,
                            alert_code="MULE_RAPID_PASSTHROUGH",
                            primary_account_id=node,
                            primary_institution_id=institution_id,
                            currency=self.currency,
                            analysis_window_start=in_tx.timestamp,
                            analysis_window_end=out_tx.timestamp,
                            detection_rule_version=self.config.rule_version,
                            scoring_model_version="v1.0",
                            risk_score=raw_score,
                            severity=severity,
                            evidence_data=evidence,
                            involved_account_ids=involved_accounts,
                            involved_transaction_ids=tx_ids,
                            dedup_fingerprint=fingerprint,
                        )
                    )

        return findings


class CircularLayeringDetector(BaseDetector):
    """Detects bounded directed cycles (e.g. A -> B -> C -> A) representing layering schemes."""

    def __init__(self, currency: str, config: CircularLayeringConfig | None = None) -> None:
        super().__init__(currency)
        self.config = config or CircularLayeringConfig()

    def detect(self, graph: nx.MultiDiGraph) -> list[DetectorFinding]:  # type: ignore[type-arg]
        findings: list[DetectorFinding] = []
        min_len = self.config.min_cycle_length
        max_len = self.config.max_cycle_length
        window_seconds = self.config.window_seconds

        # Project to simple DiGraph to find cycles safely without multi-edge explosion
        simple_digraph: nx.DiGraph = nx.DiGraph()  # type: ignore[type-arg]
        for u, v in graph.edges():
            if u == v:
                continue
            simple_digraph.add_edge(u, v)

        if simple_digraph.number_of_nodes() == 0 or simple_digraph.number_of_edges() == 0:
            return findings

        # Bounded simple cycles search
        # To avoid combinatorial explosion in dense/high-degree graphs, bound search:
        # 1. Use cycle basis or simple_cycles with length filtering and max cycle cap
        max_total_cycles = 100
        found_cycles_count = 0
        seen_canonical_cycles: set[tuple[uuid.UUID, ...]] = set()

        for cycle in nx.simple_cycles(simple_digraph):
            cycle_len = len(cycle)
            if cycle_len < min_len or cycle_len > max_len:
                continue

            found_cycles_count += 1
            if found_cycles_count > max_total_cycles:
                break

            # Canonical representation of cycle (rotate so minimum UUID is first)
            min_idx = cycle.index(min(cycle))
            canonical = tuple(cycle[min_idx:] + cycle[:min_idx])
            if canonical in seen_canonical_cycles:
                continue
            seen_canonical_cycles.add(canonical)

            # Retrieve supporting edges from the multigraph along the cycle
            cycle_edges: list[TransactionEdgeData] = []
            cycle_amounts: list[Decimal] = []
            valid_cycle = True

            for step in range(cycle_len):
                u = cycle[step]
                v = cycle[(step + 1) % cycle_len]
                edge_dict = graph.get_edge_data(u, v)
                if not edge_dict:
                    valid_cycle = False
                    break

                # Pick the earliest or representative edge along (u, v)
                all_step_edges = [d["data"] for d in edge_dict.values()]
                all_step_edges.sort(key=lambda e: e.timestamp)
                rep_edge: TransactionEdgeData = all_step_edges[0]
                cycle_edges.append(rep_edge)
                cycle_amounts.append(rep_edge.amount)

            if not valid_cycle:
                continue

            # Verify time-window bounds for the cycle
            timestamps = [e.timestamp for e in cycle_edges]
            cycle_start = min(timestamps)
            cycle_end = max(timestamps)
            if (cycle_end - cycle_start).total_seconds() > window_seconds:
                continue

            # Focal node is canonical[0]
            focal_node = canonical[0]
            node_attrs = graph.nodes[focal_node]
            institution_id = (
                node_attrs.get("institution_id") or cycle_edges[0].source_institution_id
            )

            total_cycled_amount = sum(cycle_amounts, Decimal("0"))
            min_hop_amount = min(cycle_amounts)
            tx_ids = [e.transaction_id for e in cycle_edges]

            # Scoring: Base 85 for circular fund layering + hop modifier
            hop_bonus = min(15, (cycle_len - 3) * 5)
            raw_score = min(100, 85 + hop_bonus)
            severity = AlertSeverity.CRITICAL if raw_score >= 85 else AlertSeverity.HIGH

            evidence = {
                "detector": DetectorType.CIRCULAR_LAYERING.value,
                "cycle_length": cycle_len,
                "min_cycle_length_threshold": min_len,
                "max_cycle_length_threshold": max_len,
                "cycle_path": [str(node_id) for node_id in cycle],
                "total_cycled_amount": str(total_cycled_amount),
                "bottleneck_amount": str(min_hop_amount),
                "currency": self.currency,
                "window_seconds": window_seconds,
                "cycle_start": cycle_start.isoformat(),
                "cycle_end": cycle_end.isoformat(),
                "transaction_ids": [str(t) for t in tx_ids],
                "score_breakdown": {
                    "base_score": 85,
                    "hop_bonus": hop_bonus,
                    "final_score": raw_score,
                },
                "pattern_description": (
                    f"Circular Layering: {cycle_len}-hop directed cycle detected "
                    f"involving {total_cycled_amount} {self.currency} within {window_seconds}s."
                ),
            }

            fingerprint = compute_alert_fingerprint(
                institution_id=institution_id,
                detector_type=DetectorType.CIRCULAR_LAYERING,
                primary_account_id=focal_node,
                currency=self.currency,
                involved_transaction_ids=tx_ids,
                rule_version=self.config.rule_version,
            )

            findings.append(
                DetectorFinding(
                    detector_type=DetectorType.CIRCULAR_LAYERING,
                    alert_code="MULE_CIRCULAR_LAYERING",
                    primary_account_id=focal_node,
                    primary_institution_id=institution_id,
                    currency=self.currency,
                    analysis_window_start=cycle_start,
                    analysis_window_end=cycle_end,
                    detection_rule_version=self.config.rule_version,
                    scoring_model_version="v1.0",
                    risk_score=raw_score,
                    severity=severity,
                    evidence_data=evidence,
                    involved_account_ids=list(cycle),
                    involved_transaction_ids=tx_ids,
                    dedup_fingerprint=fingerprint,
                )
            )

        return findings
