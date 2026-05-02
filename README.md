# FinanzasMMEX

App Desktop de Consolidación Financiera Local. Sincronización offline-first de Gmail, scraping headful, Mercado Pago API y PDFs hacia `finanza.mmb` (Money Manager Ex).

## Stack Técnico
- **Motor:** Python 3.11+ (Pydantic, Keyring, Playwright, RapidFuzz, SQLite).
- **UI:** C# WPF .NET 8 (Consumo de CLI Python vía JSON).
- **Persistencia:** SQLite (Capa de staging) -> SQLite (MMEX).

## Estructura
- `src/finanzasmmex/`: Código fuente del motor Python.
- `desktop/`: Código fuente de la aplicación WPF.
- `contracts/`: Esquemas JSON compartidos.
- `tests/`: Suite de pruebas.

## Setup Inicial (Fase 0)
1. Instalar Python 3.11+ y .NET 8 SDK.
2. Instalar dependencias de Python: `pip install -e .[dev]`.
3. Inicializar base de datos: `finanzasmmex init`.

## Roadmap
Ver [Issues](https://github.com/ricArdo1321/FinanzasMMEX/issues) para el seguimiento de fases.
