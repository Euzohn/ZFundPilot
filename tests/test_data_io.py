"""CSV 导入/导出测试：模板解析、中文表头、缺列检测。"""
from zfundpilot.data_io import build_template_dataframe, parse_transactions_csv


class TestParseCSV:
    def test_template_parses_cleanly(self):
        csv_bytes = build_template_dataframe().to_csv(index=False).encode("utf-8-sig")
        txs, errors = parse_transactions_csv(csv_bytes)
        assert len(txs) == 4
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
