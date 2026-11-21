"""CSV 导入/导出测试：模板解析、中文表头、缺列检测。"""
import csv
import io

from zfundpilot.data_io import (
    build_template_dataframe,
    parse_transactions_csv,
    transactions_to_csv_bytes,
)
from zfundpilot.models import Transaction


class TestParseCSV:
    def test_template_parses_cleanly(self):
        csv_bytes = build_template_dataframe().to_csv(index=False).encode("utf-8-sig")
        txs, errors = parse_transactions_csv(csv_bytes)
        assert len(txs) == 6
        assert len(errors) == 0

    def test_chinese_headers(self):
        csv_text = (
            "基金代码,操作,日期,金额,份额,净值,渠道\n"
            "001,买入,2025-01-01,1000,500,2.0,支付宝\n"
        )
        txs, errors = parse_transactions_csv(csv_text.encode("utf-8-sig"))
        assert len(txs) == 1
        assert len(errors) == 0
        assert txs[0].fund_code == "001"
        assert txs[0].channel == "支付宝"

    def test_missing_required_column(self):
        csv_text = "基金代码,日期,金额\n001,2025-01-01,1000\n"
        txs, errors = parse_transactions_csv(csv_text.encode("utf-8-sig"))
        assert len(txs) == 0
        assert len(errors) > 0

    def test_unrecognized_action_skipped(self):
        csv_text = (
            "fund_code,action,date,amount,shares,nav\n"
            "001,hold,2025-01-01,1000,500,2.0\n"
        )
        txs, errors = parse_transactions_csv(csv_text.encode("utf-8-sig"))
        assert len(txs) == 0
        assert len(errors) > 0

    def test_two_of_three_fields_auto_fills(self):
        csv_text = (
            "fund_code,action,date,amount,shares\n"
            "001,buy,2025-01-01,1000,500\n"
        )
        txs, errors = parse_transactions_csv(csv_text.encode("utf-8-sig"))
        assert len(txs) == 1
        assert txs[0].nav == 2.0


def _export_rows(txs: list[Transaction]) -> list[dict]:
    data = transactions_to_csv_bytes(txs)
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline="")))


class TestExportFormulaInjection:
    """导出侧 CSV 公式注入防护（CWE-1236）：危险开头前缀单引号。"""

    def test_dangerous_prefixes_escaped(self):
        txs = [
            Transaction(fund_code="001", action="buy", date="2025-01-01",
                        amount=1000, nav=2.0,
                        channel='=HYPERLINK("http://evil.example")',
                        note='+CMD("calc")'),
            Transaction(fund_code="002", action="buy", date="2025-01-02",
                        amount=500, nav=1.0, channel="@SUM(A1)", note="-2+3"),
            Transaction(fund_code="003", action="buy", date="2025-01-03",
                        amount=500, nav=1.0, channel="\tTab", note="\rCR"),
        ]
        rows = _export_rows(txs)
        assert rows[0]["channel"] == "'=HYPERLINK(\"http://evil.example\")"
        assert rows[0]["note"] == "'+CMD(\"calc\")"
        assert rows[1]["channel"] == "'@SUM(A1)"
        assert rows[1]["note"] == "'-2+3"
        assert rows[2]["channel"] == "'\tTab"
        assert rows[2]["note"] == "'\rCR"
        # 数值列不受影响（不会被加前缀）
        assert float(rows[0]["amount"]) == 1000.0
        assert not rows[0]["amount"].startswith("'")

    def test_negative_numeric_cell_not_prefixed(self):
        """数值单元格（非字符串）即使为负也不加前缀，保持数字语义。"""
        tx = Transaction(fund_code="004", action="buy", date="2025-01-04",
                         amount=-5.0, nav=1.0)
        rows = _export_rows([tx])
        assert float(rows[0]["amount"]) == -5.0
        assert not rows[0]["amount"].startswith("'")

    def test_normal_text_unchanged_and_roundtrip(self):
        tx = Transaction(fund_code="001", action="buy", date="2025-01-01",
                         amount=1000, nav=2.0, channel="支付宝", note="普通买入")
        rows = _export_rows([tx])
        assert rows[0]["channel"] == "支付宝"
        assert rows[0]["note"] == "普通买入"
        # 导出→导入往返正常
        txs, errors = parse_transactions_csv(transactions_to_csv_bytes([tx]))
        assert len(txs) == 1
        assert errors == []

    def test_import_does_not_strip_prefix(self):
        """防护只在导出路径：导入解析不剥离前缀（原样读回）。"""
        tx = Transaction(fund_code="001", action="buy", date="2025-01-01",
                         amount=1000, nav=2.0, note="=1+1")
        txs, errors = parse_transactions_csv(transactions_to_csv_bytes([tx]))
        assert len(txs) == 1
        assert errors == []
        assert txs[0].note == "'=1+1"
