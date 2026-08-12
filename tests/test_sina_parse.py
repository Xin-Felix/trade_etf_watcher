"""新浪期权快照字段解析测试（字段位置 2026-07 实网验证）."""
from watcher.option_meta import OptionQuoteFetcher


def _parts(**overrides) -> list[str]:
    """构造 51 字段快照，默认值取自真实样例."""
    p = ["0"] * 51
    base = {
        0: "3", 1: "0.2732", 2: "0.2818", 3: "0.3044", 4: "1", 5: "6146",
        6: "-16.73", 7: "7.6130", 8: "0.3396", 32: "2026-07-23 11:27:56",
        36: "510500", 37: "500ETF购8月7613A", 38: "27.39", 41: "4288",
        44: "0.3384", 46: "2026-08-26",
    }
    base.update(overrides)
    for k, v in base.items():
        p[k] = v
    return p


def test_parse_op_key_fields():
    f = OptionQuoteFetcher()
    q = f._parse_op(_parts())
    f.close()
    assert q["price"] == 0.2818
    assert q["buy_price"] == 0.2732 and q["buy_vol"] == 3
    assert q["sell_price"] == 0.3044 and q["sell_vol"] == 1
    assert q["open_interest"] == 6146
    # [6] 官方涨跌幅（对昨结，方向与K线一致），不是 [38] 的重述基准涨幅
    assert q["change_pct"] == -16.73
    # [41] 真实成交量（[6] 曾被误当成交量导致负值）
    assert q["volume"] == 4288
    assert q["prev_settle"] == 0.3384
    assert q["strike"] == 7.613
    assert q["name"] == "500ETF购8月7613A"
    assert q["ts"] == "2026-07-23 11:27:56"
    assert q["expire_date"] == "2026-08-26"


def test_parse_op_change_pct_fallback():
    """[6] 为空时回退 [38]."""
    f = OptionQuoteFetcher()
    parts = _parts()
    parts[6] = ""
    q = f._parse_op(parts)
    f.close()
    assert q["change_pct"] == 27.39


def test_parse_op_short_parts():
    f = OptionQuoteFetcher()
    assert f._parse_op(["1", "2", "3"]) is None
    f.close()
