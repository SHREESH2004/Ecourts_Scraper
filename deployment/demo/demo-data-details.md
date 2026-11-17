# Demo data details

- Source: scraped High Court records from the project’s merged SQLite index.
- Sample rule: retain records whose source index ID is divisible by 32; this gives a reproducible spread across the source index.
- Source index records: 1,69,53,329
- Demo records: 5,29,791
- Judges represented: 4,811
- Records with a judge: 4,80,428
- Classified appeal outcomes: 4,973 (upheld 1,577, set aside 2,301, modified 1,095)
- Decision dates represented: 1950-01-01 to 2026-04-15
- SQLite file size: 240.2 MiB

This is a sample for demonstrating the app, not the complete High Court index. The app’s outcome figures are estimates derived from scraped docket, party, and disposition text; they are not verified trial-court conviction rates. The sample contains case metadata, not judgment PDF contents.
