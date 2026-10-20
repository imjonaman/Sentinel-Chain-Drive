"""Graph model construction for transaction fund-flow analysis using NetworkX."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import networkx as nx

from sentinel_chain_drive.db.models.account import Account
from sentinel_chain_drive.db.models.transaction import Transaction, TransactionStatus
from sentinel_chain_drive.services.mulechain.models import (
    AccountNodeData,
    TransactionEdgeData,
)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class TransactionGraphBuilder:
    """Constructs deterministic directed multigraphs from synthetic banking transactions."""

    def __init__(
        self,
        currency: str,
        allowed_status: TransactionStatus = TransactionStatus.SETTLED,
    ) -> None:
        self.currency = currency.upper()
        self.allowed_status = allowed_status

    def build_graph(
        self,
        transactions: Sequence[Transaction],
        accounts: Sequence[Account] | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> nx.MultiDiGraph:  # type: ignore[type-arg]
        """Construct a NetworkX MultiDiGraph preserving parallel edges and enforcing invariants.

        Invariants:
        1. Exact currency isolation: only transactions matching self.currency are admitted.
        2. Status invariant: only allowed_status (default: SETTLED) transactions
           represent completed fund flows.
        3. Deterministic construction: sorted by timestamp then transaction ID.
        4. Time-bounded: edges strictly within [from_time, to_time].
        """
        graph: nx.MultiDiGraph = nx.MultiDiGraph()  # type: ignore[type-arg]
        from_time_utc = _ensure_utc(from_time)
        to_time_utc = _ensure_utc(to_time)

        # Seed account metadata if provided
        if accounts:
            for acc in accounts:
                node_data = AccountNodeData(
                    account_id=acc.id,
                    institution_id=acc.institution_id,
                    account_type=str(acc.account_type),
                    created_at=_ensure_utc(acc.created_at),
                )
                graph.add_node(acc.id, data=node_data, institution_id=acc.institution_id)

        # Filter and deterministically sort transactions
        filtered_txs = []
        for tx in transactions:
            if tx.currency != self.currency:
                continue

            tx_status = (
                tx.status
                if isinstance(tx.status, TransactionStatus)
                else TransactionStatus(str(tx.status))
            )
            if tx_status != self.allowed_status:
                continue

            # Check timestamp boundaries with UTC normalization
            tx_time = _ensure_utc(tx.created_at)
            assert tx_time is not None
            if from_time_utc is not None and tx_time < from_time_utc:
                continue
            if to_time_utc is not None and tx_time > to_time_utc:
                continue

            filtered_txs.append(tx)

        # Deterministic sorting
        sorted_txs = sorted(filtered_txs, key=lambda t: (_ensure_utc(t.created_at), t.id))

        for tx in sorted_txs:
            src_acc = tx.origin_account_id
            dst_acc = tx.destination_account_id

            # Ensure nodes exist
            if not graph.has_node(src_acc):
                graph.add_node(
                    src_acc,
                    data=AccountNodeData(
                        account_id=src_acc,
                        institution_id=tx.origin_institution_id,
                    ),
                    institution_id=tx.origin_institution_id,
                )

            if not graph.has_node(dst_acc):
                graph.add_node(
                    dst_acc,
                    data=AccountNodeData(
                        account_id=dst_acc,
                        institution_id=tx.destination_institution_id,
                    ),
                    institution_id=tx.destination_institution_id,
                )

            edge_data = TransactionEdgeData(
                transaction_id=tx.id,
                source_account_id=src_acc,
                destination_account_id=dst_acc,
                source_institution_id=tx.origin_institution_id,
                destination_institution_id=tx.destination_institution_id,
                amount=Decimal(str(tx.amount)),
                currency=tx.currency,
                timestamp=_ensure_utc(tx.created_at),  # type: ignore[arg-type]
                status=str(tx.status.value if hasattr(tx.status, "value") else tx.status),
                purpose_code=tx.purpose_code,
            )

            # Key the multigraph edge by transaction ID to preserve parallel transactions
            graph.add_edge(
                src_acc,
                dst_acc,
                key=tx.id,
                data=edge_data,
                transaction_id=tx.id,
                amount=Decimal(str(tx.amount)),
                currency=tx.currency,
                timestamp=tx.created_at,
            )

        return graph
