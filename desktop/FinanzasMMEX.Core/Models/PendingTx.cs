using System.Text.Json;
using System.Text.Json.Serialization;

namespace FinanzasMMEX.Core.Models;

public sealed record PendingTx(
    [property: JsonPropertyName("tx_uid")] string TxUid,
    [property: JsonPropertyName("owner")] string Owner,
    [property: JsonPropertyName("source_type")] string SourceType,
    [property: JsonPropertyName("event_date")] string? EventDate,
    [property: JsonPropertyName("posted_date")] string? PostedDate,
    [property: JsonPropertyName("amount")] string Amount,
    [property: JsonPropertyName("currency")] string Currency,
    [property: JsonPropertyName("direction")] string Direction,
    [property: JsonPropertyName("account_alias")] string AccountAlias,
    [property: JsonPropertyName("merchant_raw")] string? MerchantRaw,
    [property: JsonPropertyName("merchant_norm")] string? MerchantNorm,
    [property: JsonPropertyName("tx_type")] string TxType,
    [property: JsonPropertyName("category_guess")] string? CategoryGuess,
    [property: JsonPropertyName("subcategory_guess")] string? SubcategoryGuess,
    [property: JsonPropertyName("tags")] IReadOnlyList<string> Tags,
    [property: JsonPropertyName("needs_review")] bool NeedsReview,
    [property: JsonPropertyName("review_reason")] string? ReviewReason,
    [property: JsonPropertyName("fitid_synthetic")] string? FitidSynthetic,
    [property: JsonPropertyName("mmex_status")] string MmexStatus
);

public sealed record ReviewListData(
    [property: JsonPropertyName("items")] IReadOnlyList<PendingTx> Items,
    [property: JsonPropertyName("count")] int Count
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
}
