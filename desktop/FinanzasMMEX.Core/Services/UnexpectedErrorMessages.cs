using System.ComponentModel;

namespace FinanzasMMEX.Core.Services;

/// <summary>
/// Maps unexpected runtime exceptions thrown while invoking the CLI into safe,
/// user-facing strings. The raw <c>ex.Message</c> is intentionally not echoed
/// because it can contain absolute paths, environment details, or stack traces
/// that should not surface to the WPF UI.
/// </summary>
public static class UnexpectedErrorMessages
{
    public static string Describe(Exception ex)
    {
        return ex switch
        {
            OperationCanceledException =>
                "Operación cancelada.",
            Win32Exception or System.IO.FileNotFoundException =>
                "No se pudo iniciar la CLI. Verifique la instalación de Python.",
            InvalidOperationException =>
                "La CLI no pudo arrancar; reintente o revise los logs.",
            _ => "Error inesperado al invocar la CLI; revise los logs para detalles.",
        };
    }
}
