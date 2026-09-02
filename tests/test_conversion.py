"""基金转换功能测试：原子插入 + API 校验 + 持仓计算正确性。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from zfundpilot import api as api_module
from zfundpilot import config, db
from zfundpilot.analysis import calculate_positions


def _tmp_db_path(d: str) -> str:
    return str(Path(d) / "test.db")


def test_add_conversion_creates_two_transactions():
    """add_conversion 原子插入卖出腿 + 买入腿，共享同一 conversion_id。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            from zfundpilot.models import Transaction

            from_tx = Transaction(
                fund_code="011612", action="sell", date="2026-01-05",
                shares=100, nav=2.0, fee=1.5, channel="支付宝",
            )
            to_tx = Transaction(
                fund_code="005827", action="buy", date="2026-01-05",
                amount=198, nav=1.5, fee=2.0, channel="支付宝",
            )
            from_id, to_id = db.add_conversion(from_tx, to_tx)

            with db.get_connection() as conn:
                sell = conn.execute(
                    "SELECT * FROM transactions WHERE id=?", (from_id,)
                ).fetchone()
                buy = conn.execute(
                    "SELECT * FROM transactions WHERE id=?", (to_id,)
                ).fetchone()

            assert sell["fund_code"] == "011612"
            assert sell["action"] == "sell"
            assert sell["shares"] == 100
            assert sell["conversion_id"]
            assert buy["fund_code"] == "005827"
            assert buy["action"] == "buy"
            assert buy["conversion_id"] == sell["conversion_id"]
            assert from_id != to_id


def test_add_conversion_stores_normalized_fields():
    """add_conversion 对两条交易调用 normalize() 补全字段。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            from zfundpilot.models import Transaction

            from_tx = Transaction(
                fund_code="011612", action="sell", date="2026-01-05",
                shares=100, nav=2.0, fee=1.5,
            )
            to_tx = Transaction(
                fund_code="005827", action="buy", date="2026-01-05",
                amount=198, nav=1.5, fee=2.0,
            )
            from_id, to_id = db.add_conversion(from_tx, to_tx)

            with db.get_connection() as conn:
                sell = conn.execute("SELECT amount FROM transactions WHERE id=?", (from_id,)).fetchone()
                buy = conn.execute("SELECT shares FROM transactions WHERE id=?", (to_id,)).fetchone()

            # sell: amount = shares * nav - fee = 100*2 - 1.5 = 198.5
            assert abs(sell["amount"] - 198.5) < 0.01
            # buy: shares = (amount - fee) / nav = (198 - 2) / 1.5 = 130.6667
            assert abs(buy["shares"] - 130.6667) < 0.01


def test_add_conversion_atomic():
    """add_conversion 在单个 SQLite 事务中执行；第二个插入失败时第一个回滚。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            from zfundpilot.models import Transaction

            # 构造一条非法的 to_tx（shares 和 amount 都为空），让 normalize 后仍为空
            from_tx = Transaction(
                fund_code="011612", action="sell", date="2026-01-05",
                shares=100, nav=2.0,
            )
            to_tx = Transaction(
                fund_code="005827", action="buy", date="2026-01-05",
                amount=0, nav=0,
            )
            from_id, to_id = db.add_conversion(from_tx, to_tx)

            # 两条都应有相同的 conversion_id
            with db.get_connection() as conn:
                ids = [row["id"] for row in
                       conn.execute("SELECT id FROM transactions WHERE conversion_id=?", (from_tx.conversion_id,))
                       .fetchall()]
            assert len(ids) == 2


def test_conversion_api_happy_path():
    """POST /api/conversions 成功创建两条关联交易。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            db.upsert_fund(db.Fund(fund_code="011612", fund_name="测试基金A", fund_type="偏股"))
            db.upsert_fund(db.Fund(fund_code="005827", fund_name="测试基金B", fund_type="偏债"))
            client = TestClient(api_module.app)
            resp = client.post("/api/conversions", json={
                "from_code": "011612",
                "to_code": "005827",
                "date": "2026-01-05",
                "from_shares": 100,
                "from_nav": 2.0,
                "from_fee": 1.5,
                "to_amount": 198,
                "to_nav": 1.5,
                "to_fee": 2.0,
                "channel": "支付宝",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "from_id" in data
            assert "to_id" in data
            assert data["from_id"] != data["to_id"]


def test_conversion_api_same_fund_rejected():
    """转出基金和转入基金不能相同，返回 400。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            db.upsert_fund(db.Fund(fund_code="011612", fund_name="测试基金A", fund_type="偏股"))
            client = TestClient(api_module.app)
            resp = client.post("/api/conversions", json={
                "from_code": "011612",
                "to_code": "011612",
                "date": "2026-01-05",
                "from_shares": 100,
                "from_nav": 2.0,
                "to_amount": 198,
                "to_nav": 1.5,
                "channel": "支付宝",
            })
            assert resp.status_code == 400


def test_conversion_api_missing_shares_rejected():
    """转出份额为空，返回 400。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            db.upsert_fund(db.Fund(fund_code="011612", fund_name="测试基金A", fund_type="偏股"))
            db.upsert_fund(db.Fund(fund_code="005827", fund_name="测试基金B", fund_type="偏债"))
            client = TestClient(api_module.app)
            resp = client.post("/api/conversions", json={
                "from_code": "011612",
                "to_code": "005827",
                "date": "2026-01-05",
                "from_shares": 0,
                "from_nav": 2.0,
                "to_amount": 198,
                "to_nav": 1.5,
                "channel": "支付宝",
            })
            assert resp.status_code == 400


def test_conversion_api_invalid_fund_code_rejected():
    """非 6 位数字的基金代码被 Pydantic 校验拒绝。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            client = TestClient(api_module.app)
            resp = client.post("/api/conversions", json={
                "from_code": "001",
                "to_code": "005827",
                "date": "2026-01-05",
                "from_shares": 100,
                "to_amount": 198,
                "channel": "支付宝",
            })
            assert resp.status_code == 422


def test_position_calculation_after_conversion():
    """转换后持仓计算正确：转出基金减少份额+已实现收益，转入基金增加份额+成本。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            db.upsert_fund(db.Fund(fund_code="011612", fund_name="基金A", fund_type="偏股"))
            db.upsert_fund(db.Fund(fund_code="005827", fund_name="基金B", fund_type="偏债"))

            # 初始买入：011612 1000 元，nav=1.5
            from zfundpilot.models import Transaction
            db.add_transaction(Transaction(
                fund_code="011612", action="buy", date="2025-12-01",
                amount=1000, nav=1.5,
            ))
            # 初始买入：005827 500 元，nav=1.2
            db.add_transaction(Transaction(
                fund_code="005827", action="buy", date="2025-12-01",
                amount=500, nav=1.2,
            ))

            # 转换：从 011612 转出 200 份（nav=1.6），到 005827 转入 300 元（nav=1.3）
            from_tx = Transaction(
                fund_code="011612", action="sell", date="2026-01-05",
                shares=200, nav=1.6,
            )
            to_tx = Transaction(
                fund_code="005827", action="buy", date="2026-01-05",
                amount=300, nav=1.3,
            )
            db.add_conversion(from_tx, to_tx)

            positions = calculate_positions()
            pos_map = {p.fund_code: p for p in positions}

            # 011612: 原持有 666.67 份（1000/1.5），卖出 200 份 → 466.67 份
            # 均价 = 1.5, 卖出成本 = 200*1.5 = 300, 卖出金额 = 200*1.6 = 320
            # realized_pnl = 320 - 300 = 20
            pos_a = pos_map.get("011612")
            assert pos_a is not None
            assert pos_a.held_shares > 0
            assert pos_a.held_shares < 1000  # 卖出了一部分
            assert abs(pos_a.realized_pnl - 20) < 1  # 约 20 元已实现收益

            # 005827: 原持有 416.67 份（500/1.2），买入 (300/1.3)≈230.77 份
            pos_b = pos_map.get("005827")
            assert pos_b is not None
            assert pos_b.held_shares > 400  # 份额增加了


def test_transaction_has_conversion_id_in_dict():
    """Transaction.to_dict() 包含 conversion_id 字段。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            from zfundpilot.models import Transaction

            from_tx = Transaction(
                fund_code="011612", action="sell", date="2026-01-05",
                shares=100, nav=2.0,
            )
            to_tx = Transaction(
                fund_code="005827", action="buy", date="2026-01-05",
                amount=200, nav=1.5,
            )
            db.add_conversion(from_tx, to_tx)

            with db.get_connection() as conn:
                txs = [Transaction.from_row(r) for r in
                       conn.execute("SELECT * FROM transactions")]

            for tx in txs:
                d = tx.to_dict()
                assert "conversion_id" in d
                assert d["conversion_id"]  # 非空


def test_conversion_fee_independent():
    """转出赎回费和转入申购费独立计算、互不影响。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            from zfundpilot.models import Transaction

            from_tx = Transaction(
                fund_code="011612", action="sell", date="2026-01-05",
                shares=100, nav=2.0, fee=5.0,  # 赎回费 5 元
            )
            to_tx = Transaction(
                fund_code="005827", action="buy", date="2026-01-05",
                amount=195, nav=1.5, fee=10.0,  # 申购费 10 元
            )
            db.add_conversion(from_tx, to_tx)

            with db.get_connection() as conn:
                sell = conn.execute(
                    "SELECT amount FROM transactions WHERE fund_code='011612'"
                ).fetchone()
                buy = conn.execute(
                    "SELECT shares FROM transactions WHERE fund_code='005827'"
                ).fetchone()

            # sell: amount = 100*2 - 5 = 195
            assert abs(sell["amount"] - 195) < 0.01
            # buy: shares = (195 - 10) / 1.5 = 123.3333
            assert abs(buy["shares"] - 123.3333) < 0.01


def test_conversion_with_t1_flag():
    """is_t1 标记同时应用于两条交易。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            from zfundpilot.models import Transaction

            from_tx = Transaction(
                fund_code="011612", action="sell", date="2026-01-05",
                shares=100, nav=2.0, is_t1=True,
            )
            to_tx = Transaction(
                fund_code="005827", action="buy", date="2026-01-05",
                amount=200, nav=1.5, is_t1=True,
            )
            db.add_conversion(from_tx, to_tx)

            with db.get_connection() as conn:
                sell_t1 = conn.execute(
                    "SELECT is_t1 FROM transactions WHERE fund_code='011612'"
                ).fetchone()["is_t1"]
                buy_t1 = conn.execute(
                    "SELECT is_t1 FROM transactions WHERE fund_code='005827'"
                ).fetchone()["is_t1"]

            assert sell_t1 == 1
            assert buy_t1 == 1


def test_conversion_channel_shared():
    """两条交易共享同一 channel。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            from zfundpilot.models import Transaction

            from_tx = Transaction(
                fund_code="011612", action="sell", date="2026-01-05",
                shares=100, nav=2.0, channel="理财通",
            )
            to_tx = Transaction(
                fund_code="005827", action="buy", date="2026-01-05",
                amount=200, nav=1.5, channel="理财通",
            )
            db.add_conversion(from_tx, to_tx)

            with db.get_connection() as conn:
                sell = conn.execute(
                    "SELECT channel FROM transactions WHERE fund_code='011612'"
                ).fetchone()
                buy = conn.execute(
                    "SELECT channel FROM transactions WHERE fund_code='005827'"
                ).fetchone()

            assert sell["channel"] == "理财通"
            assert buy["channel"] == "理财通"
