namespace FinanzasMMEX.Core.Cli;

/// <summary>
/// Exit codes emitted by the FinanzasMMEX Python CLI. The set is part of the
/// JSON contract; the WPF UI maps each code to an actionable message.
/// </summary>
public enum CliExitCode
{
    Success = 0,
    ValidationError = 2,
    CredentialsRequired = 3,
    MmexLocked = 4,
    TemporaryFailure = 5,
}

public static class CliExitCodes
{
    public static bool IsKnown(int value) =>
        value is 0 or 2 or 3 or 4 or 5;

    public static CliExitCode FromInt(int value) =>
        IsKnown(value)
            ? (CliExitCode)value
            : CliExitCode.TemporaryFailure;
}
