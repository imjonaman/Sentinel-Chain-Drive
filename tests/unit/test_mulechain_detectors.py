"""Unit tests for MuleChain transaction graph construction and topological detectors."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from sentinel_chain_drive.db.models.alert import (
    AlertSeverity,
    DetectorType,
)
from sentinel_chain_drive.db.models.transaction import (
    Transaction,
    TransactionStatus,
    TransactionType,
)
from sentinel_chain_drive.services.mulechain.detectors import (
    CircularLayeringDetector,
    FanInDetector,
    FanOutDetector,
    RapidPassThroughDetector,
)
from sentinel_chain_drive.services.mulechain.graph_builder import TransactionGraphBuilder
from sentinel_chain_drive.services.mulechain.models import (
    CircularLayeringConfig,
    FanInConfig,
    FanOutConfig,
    RapidPassThroughConfig,
)


def _make_dummy_tx(
    origin_acc: uuid.UUID,
    dest_acc: uuid.UUID,
    inst_id: uuid.UUID,
    amount: Decimal,
    currency: str = "USD",
    status: TransactionStatus = TransactionStatus.SETTLED,
    created_at: datetime | None = None,
    dest_inst_id: uuid.UUID | None = None,
) -> Transaction:
    """Helper to construct synthetic Transaction instances for unit testing."""
    tx = Transaction(
        idempotency_key=f"idemp-{uuid.uuid4()}",
        origin_account_id=origin_acc,
        destination_account_id=dest_acc,
        origin_institution_id=inst_id,
        destination_institution_id=dest_inst_id or inst_id,
        amount=amount,
        currency=currency,
        status=status,
        transaction_type=TransactionType.TRANSFER,
    )
    tx.id = uuid.uuid4()
    if created_at is not None:
        tx.created_at = created_at
    return tx


class TestTransactionGraphBuilder:
    """Tests graph construction invariants: currency isolation, status filtering,
    and parallel edges.
    """

    def test_preserves_parallel_edges(self) -> None:
        inst_id = uuid.uuid4()
        acc1 = uuid.uuid4()
        acc2 = uuid.uuid4()
        now = datetime.now(UTC)

        tx1 = _make_dummy_tx(acc1, acc2, inst_id, Decimal("100.00"), created_at=now)
        tx2 = _make_dummy_tx(
            acc1, acc2, inst_id, Decimal("250.00"), created_at=now + timedelta(seconds=10)
        )

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph([tx1, tx2])

        assert graph.number_of_nodes() == 2
        assert graph.number_of_edges() == 2
        edge_data = graph.get_edge_data(acc1, acc2)
        assert len(edge_data) == 2
        assert tx1.id in edge_data
        assert tx2.id in edge_data

    def test_currency_isolation(self) -> None:
        inst_id = uuid.uuid4()
        acc1 = uuid.uuid4()
        acc2 = uuid.uuid4()
        now = datetime.now(UTC)

        tx_usd = _make_dummy_tx(
            acc1, acc2, inst_id, Decimal("100.00"), currency="USD", created_at=now
        )
        tx_eur = _make_dummy_tx(
            acc1, acc2, inst_id, Decimal("100.00"), currency="EUR", created_at=now
        )

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph([tx_usd, tx_eur])

        assert graph.number_of_edges() == 1
        edge_data = graph.get_edge_data(acc1, acc2)
        assert tx_usd.id in edge_data
        assert tx_eur.id not in edge_data

    def test_status_invariant_excludes_non_settled(self) -> None:
        inst_id = uuid.uuid4()
        acc1 = uuid.uuid4()
        acc2 = uuid.uuid4()
        now = datetime.now(UTC)

        tx_settled = _make_dummy_tx(
            acc1, acc2, inst_id, Decimal("100"), status=TransactionStatus.SETTLED, created_at=now
        )
        tx_submitted = _make_dummy_tx(
            acc1, acc2, inst_id, Decimal("100"), status=TransactionStatus.SUBMITTED, created_at=now
        )
        tx_pending_auth = _make_dummy_tx(
            acc1,
            acc2,
            inst_id,
            Decimal("100"),
            status=TransactionStatus.PENDING_AUTHORIZATION,
            created_at=now,
        )
        tx_rejected = _make_dummy_tx(
            acc1, acc2, inst_id, Decimal("100"), status=TransactionStatus.REJECTED, created_at=now
        )
        tx_cancelled = _make_dummy_tx(
            acc1, acc2, inst_id, Decimal("100"), status=TransactionStatus.CANCELLED, created_at=now
        )

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph(
            [tx_settled, tx_submitted, tx_pending_auth, tx_rejected, tx_cancelled]
        )

        assert graph.number_of_edges() == 1
        assert tx_settled.id in graph.get_edge_data(acc1, acc2)

    def test_cutoff_bounds(self) -> None:
        inst_id = uuid.uuid4()
        acc1 = uuid.uuid4()
        acc2 = uuid.uuid4()
        base_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)

        tx_before = _make_dummy_tx(
            acc1, acc2, inst_id, Decimal("100"), created_at=base_time - timedelta(days=2)
        )
        tx_inside = _make_dummy_tx(acc1, acc2, inst_id, Decimal("100"), created_at=base_time)
        tx_after = _make_dummy_tx(
            acc1, acc2, inst_id, Decimal("100"), created_at=base_time + timedelta(days=2)
        )

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph(
            [tx_before, tx_inside, tx_after],
            from_time=base_time - timedelta(hours=1),
            to_time=base_time + timedelta(hours=1),
        )

        assert graph.number_of_edges() == 1
        assert tx_inside.id in graph.get_edge_data(acc1, acc2)


class TestFanInDetector:
    """Tests Fan-In (smurfing ingress) topological pattern detection."""

    def test_detects_fan_in_when_threshold_exceeded(self) -> None:
        inst_id = uuid.uuid4()
        dest_acc = uuid.uuid4()
        sources = [uuid.uuid4() for _ in range(5)]
        now = datetime.now(UTC)

        txs = [
            _make_dummy_tx(
                src,
                dest_acc,
                inst_id,
                Decimal("900.00"),
                created_at=now + timedelta(minutes=i * 10),
            )
            for i, src in enumerate(sources)
        ]

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph(txs)

        detector = FanInDetector(
            currency="USD", config=FanInConfig(min_sources=5, window_seconds=86400)
        )
        findings = detector.detect(graph)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.detector_type == DetectorType.FAN_IN
        assert finding.primary_account_id == dest_acc
        assert finding.evidence_data["source_count"] == 5
        assert Decimal(finding.evidence_data["aggregate_amount"]) == Decimal("4500.00")
        assert finding.risk_score >= 65
        assert finding.severity in (AlertSeverity.HIGH, AlertSeverity.CRITICAL)

    def test_benign_traffic_below_threshold_does_not_trigger(self) -> None:
        inst_id = uuid.uuid4()
        dest_acc = uuid.uuid4()
        sources = [uuid.uuid4() for _ in range(4)]
        now = datetime.now(UTC)

        txs = [
            _make_dummy_tx(
                src,
                dest_acc,
                inst_id,
                Decimal("900.00"),
                created_at=now + timedelta(minutes=i * 10),
            )
            for i, src in enumerate(sources)
        ]

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph(txs)

        detector = FanInDetector(
            currency="USD", config=FanInConfig(min_sources=5, window_seconds=86400)
        )
        findings = detector.detect(graph)

        assert len(findings) == 0

    def test_ignores_self_transfers(self) -> None:
        inst_id = uuid.uuid4()
        dest_acc = uuid.uuid4()
        now = datetime.now(UTC)

        txs = [
            _make_dummy_tx(
                dest_acc,
                dest_acc,
                inst_id,
                Decimal("100.00"),
                created_at=now + timedelta(minutes=i),
            )
            for i in range(5)
        ]

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph(txs)

        detector = FanInDetector(
            currency="USD", config=FanInConfig(min_sources=5, window_seconds=86400)
        )
        findings = detector.detect(graph)
        assert len(findings) == 0


class TestFanOutDetector:
    """Tests Fan-Out (rapid dispersal) topological pattern detection."""

    def test_detects_fan_out_when_threshold_exceeded(self) -> None:
        inst_id = uuid.uuid4()
        src_acc = uuid.uuid4()
        destinations = [uuid.uuid4() for _ in range(6)]
        now = datetime.now(UTC)

        txs = [
            _make_dummy_tx(
                src_acc, dst, inst_id, Decimal("1000.00"), created_at=now + timedelta(minutes=i * 5)
            )
            for i, dst in enumerate(destinations)
        ]

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph(txs)

        detector = FanOutDetector(
            currency="USD", config=FanOutConfig(min_destinations=5, window_seconds=86400)
        )
        findings = detector.detect(graph)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.detector_type == DetectorType.FAN_OUT
        assert finding.primary_account_id == src_acc
        assert finding.evidence_data["destination_count"] == 6
        assert Decimal(finding.evidence_data["aggregate_amount"]) == Decimal("6000.00")
        assert finding.risk_score >= 60

    def test_benign_fan_out_below_threshold(self) -> None:
        inst_id = uuid.uuid4()
        src_acc = uuid.uuid4()
        destinations = [uuid.uuid4() for _ in range(3)]
        now = datetime.now(UTC)

        txs = [
            _make_dummy_tx(
                src_acc, dst, inst_id, Decimal("500.00"), created_at=now + timedelta(minutes=i * 5)
            )
            for i, dst in enumerate(destinations)
        ]

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph(txs)

        detector = FanOutDetector(currency="USD", config=FanOutConfig(min_destinations=5))
        findings = detector.detect(graph)
        assert len(findings) == 0


class TestRapidPassThroughDetector:
    """Tests Rapid Pass-Through (transit mule) pattern detection."""

    def test_detects_rapid_pass_through(self) -> None:
        inst_id = uuid.uuid4()
        source = uuid.uuid4()
        mule = uuid.uuid4()
        dest = uuid.uuid4()
        t1 = datetime(2026, 10, 15, 14, 0, 0, tzinfo=UTC)
        t2 = t1 + timedelta(minutes=15)

        tx_in = _make_dummy_tx(source, mule, inst_id, Decimal("10000.00"), created_at=t1)
        tx_out = _make_dummy_tx(mule, dest, inst_id, Decimal("9500.00"), created_at=t2)

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph([tx_in, tx_out])

        detector = RapidPassThroughDetector(currency="USD")
        findings = detector.detect(graph)

        assert len(findings) == 1
        f = findings[0]
        assert f.detector_type == DetectorType.RAPID_PASSTHROUGH
        assert f.primary_account_id == mule
        assert f.evidence_data["pass_through_ratio"] == 0.95
        assert f.evidence_data["delta_seconds"] == 900.0
        assert f.risk_score >= 75
        assert f.severity in (AlertSeverity.HIGH, AlertSeverity.CRITICAL)

    def test_does_not_trigger_when_time_delta_exceeds_threshold(self) -> None:
        inst_id = uuid.uuid4()
        source = uuid.uuid4()
        mule = uuid.uuid4()
        dest = uuid.uuid4()
        t1 = datetime(2026, 10, 15, 14, 0, 0, tzinfo=UTC)
        t2 = t1 + timedelta(minutes=45)

        tx_in = _make_dummy_tx(source, mule, inst_id, Decimal("10000.00"), created_at=t1)
        tx_out = _make_dummy_tx(mule, dest, inst_id, Decimal("9500.00"), created_at=t2)

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph([tx_in, tx_out])

        detector = RapidPassThroughDetector(
            currency="USD",
            config=RapidPassThroughConfig(max_delta_seconds=1800),
        )
        findings = detector.detect(graph)
        assert len(findings) == 0

    def test_does_not_trigger_when_retention_ratio_too_low(self) -> None:
        inst_id = uuid.uuid4()
        source = uuid.uuid4()
        mule = uuid.uuid4()
        dest = uuid.uuid4()
        t1 = datetime(2026, 10, 15, 14, 0, 0, tzinfo=UTC)
        t2 = t1 + timedelta(minutes=5)

        tx_in = _make_dummy_tx(source, mule, inst_id, Decimal("10000.00"), created_at=t1)
        tx_out = _make_dummy_tx(mule, dest, inst_id, Decimal("5000.00"), created_at=t2)

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph([tx_in, tx_out])

        detector = RapidPassThroughDetector(currency="USD")
        findings = detector.detect(graph)
        assert len(findings) == 0


class TestCircularLayeringDetector:
    """Tests Circular Layering (directed cycle) pattern detection."""

    def test_detects_3_hop_cycle(self) -> None:
        inst_id = uuid.uuid4()
        a = uuid.uuid4()
        b = uuid.uuid4()
        c = uuid.uuid4()
        now = datetime.now(UTC)

        tx1 = _make_dummy_tx(a, b, inst_id, Decimal("5000.00"), created_at=now)
        tx2 = _make_dummy_tx(
            b, c, inst_id, Decimal("4900.00"), created_at=now + timedelta(hours=1)
        )
        tx3 = _make_dummy_tx(
            c, a, inst_id, Decimal("4800.00"), created_at=now + timedelta(hours=2)
        )

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph([tx1, tx2, tx3])

        detector = CircularLayeringDetector(currency="USD")
        findings = detector.detect(graph)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.detector_type == DetectorType.CIRCULAR_LAYERING
        assert finding.evidence_data["cycle_length"] == 3
        assert Decimal(finding.evidence_data["total_cycled_amount"]) == Decimal("14700.00")
        assert finding.risk_score >= 85
        assert finding.severity == AlertSeverity.CRITICAL

    def test_excludes_cycles_exceeding_max_cycle_length(self) -> None:
        inst_id = uuid.uuid4()
        nodes = [uuid.uuid4() for _ in range(6)]
        now = datetime.now(UTC)

        txs = []
        for i in range(6):
            u = nodes[i]
            v = nodes[(i + 1) % 6]
            txs.append(
                _make_dummy_tx(
                    u, v, inst_id, Decimal("1000.00"), created_at=now + timedelta(hours=i)
                )
            )

        builder = TransactionGraphBuilder(currency="USD")
        graph = builder.build_graph(txs)

        detector = CircularLayeringDetector(
            currency="USD",
            config=CircularLayeringConfig(min_cycle_length=3, max_cycle_length=5),
        )
        findings = detector.detect(graph)
        assert len(findings) == 0


class TestDetectorConfigurations:
    """Tests validation of detector configuration inputs."""

    def test_invalid_fan_in_config(self) -> None:
        with pytest.raises(ValueError, match="min_sources"):
            FanInConfig(min_sources=1)
        with pytest.raises(ValueError, match="window_seconds"):
            FanInConfig(window_seconds=0)

    def test_invalid_fan_out_config(self) -> None:
        with pytest.raises(ValueError, match="min_destinations"):
            FanOutConfig(min_destinations=1)

    def test_invalid_rapid_pass_through_config(self) -> None:
        with pytest.raises(ValueError, match="max_delta_seconds"):
            RapidPassThroughConfig(max_delta_seconds=-10)
        with pytest.raises(ValueError, match="min_pass_through_ratio"):
            RapidPassThroughConfig(min_pass_through_ratio=1.5)

    def test_invalid_circular_layering_config(self) -> None:
        with pytest.raises(ValueError, match="min_cycle_length"):
            CircularLayeringConfig(min_cycle_length=1)
        with pytest.raises(ValueError, match="max_cycle_length cannot be less than"):
            CircularLayeringConfig(min_cycle_length=5, max_cycle_length=3)
        with pytest.raises(ValueError, match="cannot exceed 10"):
            CircularLayeringConfig(max_cycle_length=15)
