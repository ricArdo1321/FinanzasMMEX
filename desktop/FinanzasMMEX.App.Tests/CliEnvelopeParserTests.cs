using FinanzasMMEX.Core.Cli;
using Xunit;

namespace FinanzasMMEX.App.Tests;

public class CliEnvelopeParserTests
{
    [Fact]
    public void Parses_success_envelope()
    {
        var stdout = """
        {
          "ok": true,
          "data": {"hello": "world"},
          "errors": [],
          "warnings": [],
          "run_id": "abc-123"
        }
        """;

        var envelope = CliEnvelopeParser.TryParse(stdout);

        Assert.NotNull(envelope);
        Assert.True(envelope!.Ok);
        Assert.Equal("abc-123", envelope.RunId);
        Assert.Empty(envelope.Errors);
    }

    [Fact]
    public void Parses_validation_error_envelope()
    {
        var stdout = """
        {
          "ok": false,
          "data": null,
          "errors": [
            {"code": "VALIDATION_ERROR", "message": "bad input", "details": {"field": "x"}}
          ],
          "warnings": [],
          "run_id": "id"
        }
        """;

        var envelope = CliEnvelopeParser.TryParse(stdout);

        Assert.NotNull(envelope);
        Assert.False(envelope!.Ok);
        Assert.Single(envelope.Errors);
        Assert.Equal("VALIDATION_ERROR", envelope.FirstErrorCode);
    }

    [Fact]
    public void Returns_null_for_garbage_stdout()
    {
        var envelope = CliEnvelopeParser.TryParse("not json");
        Assert.Null(envelope);
    }

    [Fact]
    public void Returns_null_for_empty_stdout()
    {
        Assert.Null(CliEnvelopeParser.TryParse(""));
        Assert.Null(CliEnvelopeParser.TryParse("   "));
    }
}
