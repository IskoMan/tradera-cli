import re

import httpx
import pytest

from traderacli import api
from traderacli.cli import format_item, main, price


@pytest.fixture(autouse=True)
def creds(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return  # live tests use the real credentials
    monkeypatch.setenv("TRADERA_APP_ID", "1234")
    monkeypatch.setenv("TRADERA_APP_KEY", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def item_xml(i, desc="ThinkPad T14s", buy_now=0, next_bid=1500, bids=3):
    return (
        f"<Items><Id>{i}</Id><ShortDescription>{desc}</ShortDescription>"
        f"<BuyItNowPrice>{buy_now}</BuyItNowPrice><SellerId>9</SellerId>"
        f"<MaxBid>1400</MaxBid><EndDate>2026-10-01T20:00:00</EndDate>"
        f"<NextBid>{next_bid}</NextBid><HasBids>true</HasBids><IsEnded>false</IsEnded>"
        f"<ItemUrl>https://www.tradera.com/item/1/{i}/x</ItemUrl><CategoryId>1</CategoryId>"
        f"<BidCount>{bids}</BidCount></Items>"
    )


def response_xml(items, pages=1):
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
        '<SearchAdvancedResponse xmlns="http://api.tradera.com"><SearchAdvancedResult>'
        f"<TotalNumberOfItems>{len(items)}</TotalNumberOfItems>"
        f"<TotalNumberOfPages>{pages}</TotalNumberOfPages>{''.join(items)}"
        "</SearchAdvancedResult></SearchAdvancedResponse></soap:Body></soap:Envelope>"
    )


def mock_client(pages, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        body = request.content.decode()
        page = int(re.search(r"<PageNumber>(\d+)</PageNumber>", body).group(1))
        return httpx.Response(200, text=response_xml(pages[page - 1], pages=len(pages)))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_envelope_orders_fields_by_wsdl_sequence():
    env = api.build_envelope("1", "k", {"PageNumber": 2, "SearchWords": "a&b", "PriceMaximum": 7})
    assert env.index("<SearchWords>") < env.index("<PriceMaximum>") < env.index("<PageNumber>")
    assert "<SearchWords>a&amp;b</SearchWords>" in env
    assert "<CountyId>" not in env  # None/unset fields are omitted


def test_envelope_rejects_unknown_field():
    with pytest.raises(ValueError):
        api.build_envelope("1", "k", {"Bogus": 1})


def test_search_paginates_and_sends_auth():
    seen = []
    pages = [[item_xml(1)], [item_xml(2)]]
    items = list(api.search({"SearchWords": "t14s"}, max_pages=5, client=mock_client(pages, seen)))
    assert [it["Id"] for it in items] == ["1", "2"]
    assert seen[0].headers["SOAPAction"] == '"http://api.tradera.com/SearchAdvanced"'
    assert "<AppId>1234</AppId>" in seen[0].content.decode()


def test_search_respects_max_pages():
    pages = [[item_xml(1)], [item_xml(2)]]
    items = list(api.search({}, max_pages=1, client=mock_client(pages)))
    assert [it["Id"] for it in items] == ["1"]


def test_soap_fault_raises():
    fault = (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
        "<soap:Fault><faultstring>Invalid AppKey</faultstring></soap:Fault>"
        "</soap:Body></soap:Envelope>"
    )
    with pytest.raises(RuntimeError, match="Invalid AppKey"):
        api.parse_search_response(fault)


def test_price_prefers_buy_now_then_next_bid():
    assert price({"BuyItNowPrice": "4500", "NextBid": "100"}) == 4500
    assert price({"BuyItNowPrice": "0", "NextBid": "1500"}) == 1500


def test_format_item():
    out = format_item({"BuyItNowPrice": "0", "NextBid": "1500", "BidCount": "3",
                       "EndDate": "2026-10-01T20:00:00", "ShortDescription": "T14s",
                       "ItemUrl": "https://x"})
    assert "1 500 kr" in out and "3 bud" in out and "2026-10-01 20:00" in out


def test_missing_credentials_is_a_clear_error(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TRADERA_APP_ID")
    monkeypatch.delenv("TRADERA_APP_KEY")
    monkeypatch.setattr(api, "CONFIG_FILE", tmp_path / "env")
    assert main(["search", "x"]) == 1
    assert "api.tradera.com/register" in capsys.readouterr().err


def test_credentials_from_config_file(monkeypatch, tmp_path):
    monkeypatch.delenv("TRADERA_APP_ID")
    monkeypatch.delenv("TRADERA_APP_KEY")
    f = tmp_path / "env"
    f.write_text("# comment\nTRADERA_APP_ID=42\nTRADERA_APP_KEY=abc\n")
    monkeypatch.setattr(api, "CONFIG_FILE", f)
    assert api.credentials() == ("42", "abc")


@pytest.mark.live
def test_live_search():
    items = list(api.search({"SearchWords": "thinkpad", "ItemsPerPage": 5}))
    assert items and "ItemUrl" in items[0]
