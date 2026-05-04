using FinanzasMMEX.Core.Cli;
using Xunit;

namespace FinanzasMMEX.App.Tests;

public class CliExitCodeTests
{
    [Theory]
    [InlineData(0, CliExitCode.Success)]
    [InlineData(2, CliExitCode.ValidationError)]
    [InlineData(3, CliExitCode.CredentialsRequired)]
    [InlineData(4, CliExitCode.MmexLocked)]
    [InlineData(5, CliExitCode.TemporaryFailure)]
    public void Maps_known_exit_codes(int raw, CliExitCode expected)
    {
        Assert.True(CliExitCodes.IsKnown(raw));
        Assert.Equal(expected, CliExitCodes.FromInt(raw));
    }

    [Theory]
    [InlineData(1)]
    [InlineData(99)]
    [InlineData(-1)]
    public void Unknown_codes_map_to_temporary_failure(int raw)
    {
        Assert.False(CliExitCodes.IsKnown(raw));
        Assert.Equal(CliExitCode.TemporaryFailure, CliExitCodes.FromInt(raw));
    }
}
