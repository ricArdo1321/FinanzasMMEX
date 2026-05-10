using System.Text.Json;
using System.Text.Json.Serialization;

namespace FinanzasMMEX.Core.Models;

public sealed record PendingTx(
    [property: JsonPropertyName("tx_uid")] string TxUid,
    [property: JsonPropertyName("owner")] string Owner,
    [property: JsonPropertyName("source_type")] string SourceType,
    [property: JsonPropertyName("source_file")] string? SourceFile,
    [property: JsonPropertyName("source_ref")] string? SourceRef,
    [property: JsonPropertyName("event_date")] string? EventDate,
    [property: JsonPropertyName("booking_date")] string? BookingDate,
    [property: JsonPropertyName("posted_date")] string? PostedDate,
    [property: JsonPropertyName("amount")] string Amount,
    [property: JsonPropertyName("currency")] string Currency,
    [property: JsonPropertyName("direction")] string Direction,
    [property: JsonPropertyName("account_alias")] string AccountAlias,
    [property: JsonPropertyName("card_last4")] string? CardLast4,
    [property: JsonPropertyName("merchant_raw")] string? MerchantRaw,
    [property: JsonPropertyName("merchant_norm")] string? MerchantNorm,
    [property: JsonPropertyName("tx_type")] string TxType,
    [property: JsonPropertyName("category_guess")] string? CategoryGuess,
    [property: JsonPropertyName("subcategory_guess")] string? SubcategoryGuess,
    [property: JsonPropertyName("tags")] IReadOnlyList<string> Tags,
    [property: JsonPropertyName("needs_review")] bool NeedsReview,
    [property: JsonPropertyName("review_reason")] string? ReviewReason,
    [property: JsonPropertyName("fitid_synthetic")] string? FitidSynthetic,
    [property: JsonPropertyName("parser_name")] string? ParserName,
    [property: JsonPropertyName("parser_version")] string? ParserVersion,
    [property: JsonPropertyName("mmex_status")] string MmexStatus,
    [property: JsonPropertyName("transfer_pair_uid")] string? TransferPairUid
);

public sealed record ReviewListFilters(
    [property: JsonPropertyName("owner")] string? Owner,
    [property: JsonPropertyName("account_alias")] string? AccountAlias,
    [property: JsonPropertyName("status")] string? Status,
    [property: JsonPropertyName("needs_review_only")] bool NeedsReviewOnly,
    [property: JsonPropertyName("since")] string? Since,
    [property: JsonPropertyName("until")] string? Until,
    [property: JsonPropertyName("source_type")] string? SourceType,
    [property: JsonPropertyName("category")] string? Category,
    [property: JsonPropertyName("merchant")] string? Merchant,
    [property: JsonPropertyName("limit")] int Limit
);

public sealed record ReviewListData(
    [property: JsonPropertyName("items")] IReadOnlyList<PendingTx> Items,
    [property: JsonPropertyName("count")] int Count,
    [property: JsonPropertyName("filters")] ReviewListFilters? Filters
);

public sealed record BulkReviewError(
    [property: JsonPropertyName("code")] string Code,
    [property: JsonPropertyName("message")] string Message,
    [property: JsonPropertyName("details")] JsonElement? Details
);

public sealed record BulkReviewResult(
    [property: JsonPropertyName("index")] int Index,
    [property: JsonPropertyName("tx_uid")] string? TxUid,
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("updated_fields")] IReadOnlyList<string>? UpdatedFields,
    [property: JsonPropertyName("tx")] PendingTx? Tx,
    [property: JsonPropertyName("error")] BulkReviewError? Error
);

public sealed record BulkReviewData(
    [property: JsonPropertyName("action")] string Action,
    [property: JsonPropertyName("items_total")] int ItemsTotal,
    [property: JsonPropertyName("items_ok")] int ItemsOk,
    [property: JsonPropertyName("items_error")] int ItemsError,
    [property: JsonPropertyName("results")] IReadOnlyList<BulkReviewResult> Results
);

public sealed record ReportInfo(
    [property: JsonPropertyName("month")] string Month,
    [property: JsonPropertyName("report_path")] string ReportPath,
    [property: JsonPropertyName("filename")] string Filename,
    [property: JsonPropertyName("modified_at")] string ModifiedAt
);

public sealed record LatestReportData(
    [property: JsonPropertyName("reports_dir")] string ReportsDir,
    [property: JsonPropertyName("report")] ReportInfo? Report
);

public static class PendingTxParser
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    public static ReviewListData? ParseReviewList(JsonElement data) =>
        data.ValueKind == JsonValueKind.Undefined
            ? null
            : JsonSerializer.Deserialize<ReviewListData>(data.GetRawText(), Options);

    public static BulkReviewData? ParseBulkReview(JsonElement data) =>
        data.ValueKind == JsonValueKind.Undefined
            ? null
            : JsonSerializer.Deserialize<BulkReviewData>(data.GetRawText(), Options);

    public static PendingTx? ParsePendingTx(JsonElement data) =>
        data.ValueKind == JsonValueKind.Undefined
            ? null
            : JsonSerializer.Deserialize<PendingTx>(data.GetRawText(), Options);

    public static LatestReportData? ParseLatestReport(JsonElement data) =>
        data.ValueKind == JsonValueKind.Undefined
            ? null
            : JsonSerializer.Deserialize<LatestReportData>(data.GetRawText(), Options);
}
