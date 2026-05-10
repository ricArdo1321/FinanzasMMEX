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
              "source_file": "fixture.csv",
              "source_ref": "row-1",
              "event_date": "2026-04-15",
              "booking_date": "2026-04-16",
              "posted_date": "2026-04-15",
              "amount": "5500.00",
              "currency": "CLP",
              "direction": "debit",
              "account_alias": "BE_Ricardo_RUT",
              "card_last4": "1234",
              "merchant_raw": "Cafe",
              "merchant_norm": "CAFE",
              "tx_type": "purchase",
              "category_guess": null,
              "subcategory_guess": null,
              "tags": ["joint"],
              "needs_review": false,
              "review_reason": null,
              "fitid_synthetic": "abc",
              "parser_name": "test",
              "parser_version": "1.0",
              "mmex_status": "pending",
              "transfer_pair_uid": null
            }
          ],
          "count": 1,
          "filters": {
            "owner": "ricardo",
            "account_alias": null,
            "status": "pending",
            "needs_review_only": false,
            "since": "2026-04-01",
            "until": "2026-04-30",
            "source_type": "manual",
            "category": null,
            "merchant": "Cafe",
            "limit": 200
          }
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
        Assert.Equal("fixture.csv", tx.SourceFile);
        Assert.Equal("2026-04-16", tx.BookingDate);
        Assert.Equal("1234", tx.CardLast4);
        Assert.Equal("CLP", tx.Currency);
        Assert.Equal(new[] { "joint" }, tx.Tags);
        Assert.False(tx.NeedsReview);
        Assert.Equal("manual", parsed.Filters?.SourceType);
        Assert.Equal("Cafe", parsed.Filters?.Merchant);
    }

    [Fact]
    public void Parses_bulk_review_payload()
    {
        var json = """
        {
          "action": "bulk-update",
          "items_total": 1,
          "items_ok": 1,
          "items_error": 0,
          "results": [
            {
              "index": 0,
              "tx_uid": "u1",
              "ok": true,
              "updated_fields": ["needs_review"],
              "tx": {
                "tx_uid": "u1",
                "owner": "ricardo",
                "source_type": "manual",
                "source_file": null,
                "source_ref": null,
                "event_date": "2026-04-15",
                "booking_date": null,
                "posted_date": "2026-04-15",
                "amount": "5500.00",
                "currency": "CLP",
                "direction": "debit",
                "account_alias": "BE_Ricardo_RUT",
                "card_last4": null,
                "merchant_raw": "Cafe",
                "merchant_norm": "CAFE",
                "tx_type": "purchase",
                "category_guess": null,
                "subcategory_guess": null,
                "tags": [],
                "needs_review": false,
                "review_reason": null,
                "fitid_synthetic": "abc",
                "parser_name": "test",
                "parser_version": "1.0",
                "mmex_status": "pending",
                "transfer_pair_uid": null
              }
            }
          ]
        }
        """;

        var element = JsonDocument.Parse(json).RootElement;
        var parsed = PendingTxParser.ParseBulkReview(element);

        Assert.NotNull(parsed);
        Assert.Equal("bulk-update", parsed!.Action);
        Assert.Equal(1, parsed.ItemsOk);
        Assert.Equal("needs_review", parsed.Results[0].UpdatedFields![0]);
        Assert.False(parsed.Results[0].Tx!.NeedsReview);
    }

    [Fact]
    public void Parses_latest_report_payload()
    {
        var json = """
        {
          "reports_dir": "C:\\Finanzas\\reports",
          "report": {
            "month": "2026-05",
            "report_path": "C:\\Finanzas\\reports\\dashboard_2026-05.html",
            "filename": "dashboard_2026-05.html",
            "modified_at": "2026-05-10T10:00:00"
          }
        }
        """;

        var element = JsonDocument.Parse(json).RootElement;
        var parsed = PendingTxParser.ParseLatestReport(element);

        Assert.NotNull(parsed);
        Assert.Equal("2026-05", parsed!.Report?.Month);
        Assert.EndsWith("dashboard_2026-05.html", parsed.Report?.ReportPath);
    }
}
