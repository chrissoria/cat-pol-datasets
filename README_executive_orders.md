# U.S. Executive Orders, 1791 to the present

Every executive order with its full text, one row per order, newest first.

## Where it comes from

- **Orders signed up to March 2026** were collected once from the
  [American Presidency Project](https://www.presidency.ucsb.edu/) at UC Santa
  Barbara, which has gathered executive orders back to 1791.
- **Orders signed since** are added each day from the
  [Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1),
  the government's official journal, which publishes every executive order a
  few days after it is signed.

Orders from 1994 on also carry their Federal Register document number, the
date they were published there, and links to the Register's page and PDF.

The orders themselves are works of the U.S. government.

## Columns

| Column | Description |
|---|---|
| `date` | The day the order was signed (YYYY-MM-DD). |
| `title` | The order's title, with "Executive Order NNNNN—" in front when it has a number. |
| `executive_order_number` | The order's number. Empty for early orders, which were not numbered. |
| `president` | The president who signed it, spelled as the American Presidency Project spells it. Terms that are not consecutive are told apart, as in "Donald J. Trump (2nd Term)". |
| `party` | That president's party. |
| `text` | The full text of the order. |
| `url` | Where the row was collected from. |
| `year` | The year of `date`. |
| `source` | "American Presidency Project" or "Federal Register". |
| `document_number` | The Federal Register's document number (1994 on). |
| `publication_date` | The day the Federal Register published the order (1994 on). |
| `federal_register_url` | The order's page in the Federal Register (1994 on). |
| `pdf_url` | The order as printed, as a PDF (1994 on). |

## Things to know

- The Federal Register files a few other documents under "executive order":
  corrections to earlier orders, and presidential orders that have no
  executive order number. Those are not included.
- An order appears here once the Federal Register has published it, usually
  within a week of signing.
- Text collected from the two sources is laid out a little differently: rows
  from the Federal Register begin with the Register's heading for the order.
- Order numbers before the mid-1900s are not all unique in the source, because
  some early orders were numbered after the fact or share a number with a
  letter suffix.

## Updates

`update_executive_orders.py` in
[cat-pol-datasets](https://github.com/chrissoria/cat-pol-datasets) runs daily.
It never publishes a table with fewer rows than the one already here.
