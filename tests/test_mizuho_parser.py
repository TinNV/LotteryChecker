from lottery_checker.mizuho import MizuhoLotteryClient


def test_parse_loto_csv_normalizes_rank_labels():
    client = MizuhoLotteryClient()
    csv_text = """A52
第2078回ロト６,数字選択式全国自治宝くじ,令和8年2月19日,東京 宝くじドリーム館
支払期間,令和8年2月20日から令和9年2月19日まで
本数字,01,10,20,24,30,35,ボーナス数字,41
１等,2口,1000000円
２等,10口,50000円
３等,100口,10000円
４等,1000口,1000円
５等,10000口,100円
キャリーオーバー,123円
販売実績額,999円
１等,申込数字が本数字６個と全て一致
"""
    draw = client._parse_loto_draw_csv("loto6", csv_text, "https://example.com")
    assert draw.draw_number == 2078
    assert draw.main_numbers == [1, 10, 20, 24, 30, 35]
    assert draw.bonus_numbers == [41]
    assert [tier.rank for tier in draw.prize_tiers] == ["1等", "2等", "3等", "4等", "5等"]


def test_parse_traditional_csv_sections():
    client = MizuhoLotteryClient()
    csv_text = """A01
第1090回 全国自治宝くじ,節分の100円くじ,令和8年2月20日,東京 宝くじドリーム館
支払期間,令和8年2月26日から令和9年2月25日まで
１等,1000万円,16組,139476
１等の前後賞,250万円,１等の前後の番号,,
２等,30万円,各組共通,113530
A01
第1089回 全国自治宝くじ,テスト,令和8年2月10日,東京 宝くじドリーム館
支払期間,令和8年2月11日から令和9年2月10日まで
１等,100万円,10組,123456
"""
    draws = client._parse_traditional_csv("zenkoku", csv_text, "https://example.com")
    assert len(draws) == 2
    assert draws[0].draw_order == 1090
    assert draws[0].draw_subtitle == "節分の100円くじ"
    assert draws[0].prize_rows[0].rank == "１等"
    assert draws[0].prize_rows[0].number == "139476"
