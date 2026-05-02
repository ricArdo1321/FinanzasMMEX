// BAD: directly reads staging.db from C# (boundary violation).
// Also: synchronous WaitForExit on UI thread, .Result, no timeout,
// secret displayed in MessageBox.
using System.Diagnostics;
using System.Windows;
using Microsoft.Data.Sqlite; // VIOLATION: SQLite library in WPF project

namespace FinanzasMMEX.App;

public partial class MainWindow : Window
{
    private void LoadPending_Click(object sender, RoutedEventArgs e)
    {
        // VIOLATION: direct SQLite access bypasses Python CLI.
        using var conn = new SqliteConnection("Data Source=C:/Finanzas/staging.db");
        conn.Open();
        using var cmd = conn.CreateCommand();
        cmd.CommandText = "SELECT * FROM canonical_tx WHERE mmex_status = 'pending'";
        using var reader = cmd.ExecuteReader();
        while (reader.Read()) { /* ... */ }

        // VIOLATION: synchronous Process invocation on UI thread, no timeout.
        var p = Process.Start("finanzasmmex");
        p!.WaitForExit();
        var output = p.StandardOutput.ReadToEnd();

        // VIOLATION: full token shown to user.
        var token = "ya29.a0AfH6SMBfullSecretShouldNotBeShown";
        MessageBox.Show($"Token actual: {token}");
    }
}
