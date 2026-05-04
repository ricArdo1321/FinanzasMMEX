using System.Text.Json;
using FinanzasMMEX.Core.Models;
using Xunit;

namespace FinanzasMMEX.App.Tests;

public class PendingTxParserTests
{
    [Fact]
    public void Parses_review_list_payload()
    {
        var json = """
        {
          "items": [
            {
              "tx_uid": "u1",
              "owner": "ricardo",
              "source_type": "manual",
              "event_date": "2026-04-15",
              "posted_date": "2026-04-15",
              "amount": "5500.00",
              "currency": "CLP",
              "direction": "debit",
              "account_alias": "BE_Ricardo_RUT",
              "merchant_raw": "Cafe",
              "merchant_norm": "CAFE",
              "tx_type": "purchase",
              "category_guess": null,
              "subcategory_guess": null,
              "tags": ["joint"],
              "needs_review": false,
              "review_reason": null,
              "fitid_synthetic": "abc",
              "mmex_status": "pending"
            }
          ],
          "count": 1
        }
        """;

        var element = JsonDocument.Parse(json).RootElement;
        var parsed = PendingTxParser.ParseReviewList(element);

        Assert.NotNull(parsed);
        Assert.Equal(1, parsed!.Count);
        Assert.Single(parsed.Items);
        var tx = parsed.Items[0];
        Assert.Equal("u1", tx.TxUid);
        Assert.Equal("ricardo", tx.Owner);
        Assert.Equal("CLP", tx.Currency);
        Assert.Equal(new[] { "joint" }, tx.Tags);
        Assert.False(tx.NeedsReview);
    }
}
