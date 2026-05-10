using FinanzasMMEX.App.ViewModels;
using FinanzasMMEX.Core.Cli;
using FinanzasMMEX.Core.Services;
using Xunit;

namespace FinanzasMMEX.App.Tests;

public class PendingsViewModelTests
{
    [Fact]
    public async Task RefreshAsync_passes_advanced_filters_to_cli()
    {
        var runner = new FakeCliRunner();
        runner.Enqueue(Ok(ReviewListJson(TxJson())));
        var vm = new PendingsViewModel(runner);

        vm.OwnerFilter = "ricardo";
        vm.AccountFilter = "BE_Ricardo_RUT";
        vm.StatusFilter = "pending";
        vm.NeedsReviewOnly = true;
        vm.SinceFilter = "2026-05-01";
        vm.UntilFilter = "2026-05-31";
        vm.LimitFilter = "50";
        vm.SourceFilter = "manual";
        vm.CategoryFilter = "Cafes";
        vm.MerchantFilter = "Cafe";

        await vm.RefreshAsync();

        Assert.Equal(
            new[]
            {
                "review", "list",
                "--owner", "ricardo",
                "--account-alias", "BE_Ricardo_RUT",
                "--status", "pending",
                "--needs-review-only",
                "--since", "2026-05-01",
                "--until", "2026-05-31",
                "--source-type", "manual",
                "--category", "Cafes",
                "--merchant", "Cafe",
                "--limit", "50",
            },
            runner.Calls[0]);
        Assert.Single(vm.Items);
        Assert.Equal("u1", vm.SelectedItem?.TxUid);
    }

    [Fact]
    public async Task SaveSelectedAsync_updates_through_review_update()
    {
        var runner = new FakeCliRunner();
        runner.Enqueue(Ok(ReviewListJson(TxJson(needsReview: true, category: "Old"))));
        var vm = new PendingsViewModel(runner);
        await vm.RefreshAsync();

        vm.EditMerchantNorm = "CAFE OK";
        vm.EditCategoryGuess = "Cafes";
        vm.EditSubcategoryGuess = "Almuerzo";
        vm.EditTags = "joint, personal";
        vm.EditNeedsReview = false;
        vm.EditReviewReason = string.Empty;
        runner.Enqueue(
            Ok(UpdateJson(TxJson(
                merchantNorm: "CAFE OK",
                category: "Cafes",
                subcategory: "Almuerzo",
                needsReview: false))));

        await vm.SaveSelectedAsync();

        Assert.Equal(
            new[]
            {
                "review", "update",
                "--tx-uid", "u1",
                "--merchant-norm", "CAFE OK",
                "--category-guess", "Cafes",
                "--subcategory-guess", "Almuerzo",
                "--tags", "joint, personal",
                "--needs-review", "false",
                "--review-reason", string.Empty,
            },
            runner.Calls[1]);
        Assert.Equal("Cafes", vm.SelectedItem?.CategoryGuess);
        Assert.Equal("Transaccion actualizada.", vm.StatusMessage);
    }

    [Fact]
    public async Task Bulk_commands_write_json_batches_and_use_cli_boundary()
    {
        var runner = new FakeCliRunner();
        runner.Enqueue(
            Ok(ReviewListJson(
                TxJson(uid: "u1", needsReview: true),
                TxJson(uid: "u2", needsReview: false))));
        var vm = new PendingsViewModel(runner);
        await vm.RefreshAsync();

        runner.Enqueue(Ok(BulkJson("bulk-update", TxJson(uid: "u1", needsReview: false))));
        await vm.BulkClearReviewVisibleAsync();

        Assert.Equal(new[] { "review", "bulk-update", "--input" }, runner.Calls[1].Take(3));
        Assert.Contains("\"tx_uid\":\"u1\"", runner.CapturedInputJson[0]);
        Assert.DoesNotContain("\"tx_uid\":\"u2\"", runner.CapturedInputJson[0]);
        Assert.Contains("\"needs_review\":false", runner.CapturedInputJson[0]);

        vm.BulkResolveStatus = "inserted";
        runner.Enqueue(
            Ok(BulkJson(
                "bulk-resolve",
                TxJson(uid: "u1", status: "inserted"),
                TxJson(uid: "u2", status: "inserted"))));
        await vm.BulkResolveVisibleAsync();

        Assert.Equal(new[] { "review", "bulk-resolve", "--input" }, runner.Calls[2].Take(3));
        Assert.Contains("\"status\":\"inserted\"", runner.CapturedInputJson[1]);
    }

    [Fact]
    public async Task OpenLatestReportAsync_uses_reports_latest_and_safe_open_service()
    {
        var runner = new FakeCliRunner();
        var opener = new FakeReportOpenService();
        var vm = new PendingsViewModel(runner, opener)
        {
            ReportsDir = "C:\\Finanzas\\reports",
        };
        runner.Enqueue(
            Ok(
                """
                {
                  "reports_dir": "C:\\Finanzas\\reports",
                  "report": {
                    "month": "2026-05",
                    "report_path": "C:\\Finanzas\\reports\\dashboard_2026-05.html",
                    "filename": "dashboard_2026-05.html",
                    "modified_at": "2026-05-10T10:00:00"
                  }
                }
                """));

        await vm.OpenLatestReportAsync();

        Assert.Equal(
            new[] { "reports", "latest", "--reports-dir", "C:\\Finanzas\\reports" },
            runner.Calls[0]);
        Assert.Equal("C:\\Finanzas\\reports\\dashboard_2026-05.html", opener.OpenedPath);
        Assert.Equal("opened", vm.StatusMessage);
    }

    private static CliResult Ok(string dataJson)
    {
        var stdout = $$"""
        {"ok":true,"data":{{dataJson}},"errors":[],"warnings":[],"run_id":"test"}
        """;
        return new CliResult(
            CliExitCode.Success,
            0,
            CliEnvelopeParser.TryParse(stdout),
            stdout,
            string.Empty);
    }

    private static string ReviewListJson(params string[] items) =>
        $$"""
        {
          "items": [{{string.Join(",", items)}}],
          "count": {{items.Length}},
          "filters": {
            "owner": null,
            "account_alias": null,
            "status": "pending",
            "needs_review_only": false,
            "since": null,
            "until": null,
            "source_type": null,
            "category": null,
            "merchant": null,
            "limit": 200
          }
        }
        """;

    private static string UpdateJson(string txJson) =>
        $$"""
        {
          "tx_uid": "u1",
          "updated_fields": ["category_guess"],
          "tx": {{txJson}}
        }
        """;

    private static string BulkJson(string action, params string[] txs)
    {
        var rows = txs
            .Select((tx, index) =>
                $$"""
                {"index":{{index}},"tx_uid":"u{{index + 1}}","ok":true,"updated_fields":["needs_review"],"tx":{{tx}}}
                """);
        return $$"""
        {
          "action": "{{action}}",
          "items_total": {{txs.Length}},
          "items_ok": {{txs.Length}},
          "items_error": 0,
          "results": [{{string.Join(",", rows)}}]
        }
        """;
    }

    private static string TxJson(
        string uid = "u1",
        bool needsReview = false,
        string category = "Cafes",
        string subcategory = "",
        string merchantNorm = "CAFE",
        string status = "pending")
    {
        var review = needsReview ? "true" : "false";
        var subcategoryValue = string.IsNullOrWhiteSpace(subcategory)
            ? "null"
            : $"\"{subcategory}\"";
        return $$"""
        {
          "tx_uid": "{{uid}}",
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
          "merchant_norm": "{{merchantNorm}}",
          "tx_type": "purchase",
          "category_guess": "{{category}}",
          "subcategory_guess": {{subcategoryValue}},
          "tags": ["joint"],
          "needs_review": {{review}},
          "review_reason": null,
          "fitid_synthetic": "abc-{{uid}}",
          "parser_name": "test",
          "parser_version": "1.0",
          "mmex_status": "{{status}}",
          "transfer_pair_uid": null
        }
        """;
    }

    private sealed class FakeCliRunner : ICliRunner
    {
        private readonly Queue<CliResult> _results = new();

        public List<IReadOnlyList<string>> Calls { get; } = new();
        public List<string> CapturedInputJson { get; } = new();

        public void Enqueue(CliResult result) => _results.Enqueue(result);

        public Task<CliResult> RunAsync(
            IEnumerable<string> arguments,
            CancellationToken ct = default)
        {
            var args = arguments.ToList();
            Calls.Add(args);
            var inputIndex = args.IndexOf("--input");
            if (inputIndex >= 0 && inputIndex + 1 < args.Count)
            {
                CapturedInputJson.Add(File.ReadAllText(args[inputIndex + 1]));
            }
            return Task.FromResult(_results.Dequeue());
        }
    }

    private sealed class FakeReportOpenService : IReportOpenService
    {
        public string? OpenedPath { get; private set; }

        public Task<ReportOpenResult> OpenAsync(
            string? reportPath,
            CancellationToken cancellationToken = default)
        {
            OpenedPath = reportPath;
            return Task.FromResult(new ReportOpenResult(true, "opened"));
        }
    }
}
