"""build_san_diego puts several readings of the Clerk's listing together and reads each document's text."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import build_san_diego as sd

FOLDER = "http://docs.sandiego.gov/council_reso_ordinance"


def row(number, date="2019-09-12", title="A TITLE", url=None, second=None):
    return {"date": date, "doc_num": number, "doc_num_alt": second, "doc_type": sd.kind_of(number), "title": title,
            "pdf_url": url or f"{FOLDER}/rao{date[:4]}/{number}.pdf", "year": int(date[:4])}


def frame(*rows):
    return pd.DataFrame(list(rows), columns=sd.INDEX_COLUMNS)


def dataset(*rows, text=""):
    data = frame(*rows)
    data["text"] = text
    data["classification_status"] = None
    data["category_1"] = float("nan")
    return data


def kept(url, text="THE TEXT", source="ocr", pages=3, confidence=88.5, problem=""):
    return {"pdf_url": url, "text": text, "text_source": source, "pages": pages, "ocr_confidence": confidence, "problem": problem}


SEARCH_PAGE = """
<div class="view-content">
<div class="odd"><h3 class="field-content">
<a href="http://docs.sandiego.gov/council_reso_ordinance/rao2019/R-312806.pdf.pdf" target="_blank"><time class="datetime" datetime="2019-12-17T12:00:00Z">December 17, 2019</time>
  -  AUTHORIZING A COMPENSATION AGREEMENT</a></h3>
<div class="views-field search-result-url"><cite>docs.sandiego.gov/.../R-312806.pdf.pdf</cite></div></div>
<div class="even"><h3 class="field-content">
<a href="http://docs.sandiego.gov/council_reso_ordinance/rao2019/O-21033.pdf" target="_blank"><time class="datetime" datetime="2019-01-11T12:00:00Z">January 11, 2019</time>
  -  AMENDING THE SDMC REGARDING BRUSH MANAGEMENT</a></h3></div>
</div>
<a href="/search/ocd?search_text=&amp;f%5B0%5D=facet_searchp_ocd_doc_date_year%3A1975&amp;f%5B1%5D=x">1975 (2,978)</a>
<a href="/search/ocd?search_text=&amp;f%5B0%5D=facet_searchp_ocd_doc_date_year%3A2019&amp;f%5B1%5D=x">2019 (772)</a>
<a href="/search/ocd?search_text=&amp;f%5B0%5D=facet_searchp_ocd_doc_type%3Acity-attorney-reports">City Attorney Reports (10)</a>
<a href="?search_text=&amp;f%5B0%5D=y&amp;page=77">Last</a>
"""


def test_a_document_is_numbered_by_its_file_and_typed_by_its_number():
    assert sd.number_of(f"{FOLDER}/rao2019/R-312806.pdf.pdf") == "R-312806"
    assert sd.number_of(f"{FOLDER}/rao1986/O-9483.PDF") == "O-9483"
    assert sd.kind_of("O-22072") == "ordinance" and sd.kind_of("R-316678") == "resolution" and sd.kind_of("RB-0005") == "unknown"
    assert sd.secure(f"{FOLDER}/rao2019/O-21033.pdf").startswith("https://docs.sandiego.gov/")


def test_the_search_gives_a_date_a_title_and_the_document():
    first, second = sd.search_rows(SEARCH_PAGE)
    assert first == {"date": "2019-12-17", "doc_num": "R-312806", "doc_num_alt": None, "doc_type": "resolution",
                     "title": "AUTHORIZING A COMPENSATION AGREEMENT", "pdf_url": f"{FOLDER}/rao2019/R-312806.pdf.pdf", "year": 2019}
    assert second["doc_num"] == "O-21033" and second["title"].startswith("AMENDING THE SDMC")


def test_the_search_says_how_many_there_are_in_each_year_and_how_many_pages():
    assert sd.year_counts(SEARCH_PAGE) == {1975: 2978, 2019: 772}
    assert sd.last_page(SEARCH_PAGE) == 77


def test_readings_are_put_together_one_row_a_document_and_the_first_reading_wins():
    listing = frame(row("O-21119", second="O-2020-7"), row("O-21119", second="O-2020-7"), row("O-21122"))
    search = frame(row("O-21119", title="FROM THE SEARCH", url=f"https://docs.sandiego.gov/council_reso_ordinance/rao2019/O-21119.pdf"),
                   row("O-21128"))
    merged = sd.merge_index([listing, search])
    assert merged["doc_num"].tolist() == ["O-21119", "O-21122", "O-21128"]
    assert merged.loc[0, "doc_num_alt"] == "O-2020-7"


def test_years_short_of_the_search_count_are_found():
    index = frame(row("R-1", "1975-01-06"), row("R-2", "1975-01-06"), row("R-3", "2019-01-08"))
    assert sd.short_years(index, {1975: 5, 2019: 1, 1971: 4}) == {1975: 3, 1971: 4}


def test_a_listed_document_the_dataset_lacks_is_added_without_text():
    data = dataset(row("R-312958"), text="HAS TEXT")
    index = frame(row("R-312958"), row("R-312960"),
                  # The listing gives this one its neighbour's number; its file says which it is.
                  row("R-312958", url=f"{FOLDER}/rao2019/R-312959.pdf"),
                  row("R-312958", url=f"{FOLDER}/rao2019/copy of R-312958.pdf"))
    added, left_out = sd.add_listed(data, index)
    assert added["doc_num"].tolist() == ["R-312958", "R-312960", "R-312959"] and left_out == 1
    assert added["text"].tolist() == ["HAS TEXT", "", ""]
    assert added.dtypes.to_dict() == data.dtypes.to_dict()


def test_documents_wait_in_order_ordinances_first_and_then_from_the_newest_back():
    data = dataset(row("R-1", "2001-03-05"), row("O-1", "1985-06-10"), row("R-2", "2019-02-04"), row("O-2", "2010-07-19"),
                   row("R-3", "2020-01-14"))
    done = pd.DataFrame([kept(data.loc[4, "pdf_url"]), kept(data.loc[2, "pdf_url"], text="", source="", problem="not fetched: Timeout")])
    assert [sd.number_of(u) for u in sd.waiting(data, done)] == ["O-2", "O-1", "R-1"]
    assert [sd.number_of(u) for u in sd.waiting(data, done, retry=True)] == ["O-2", "O-1", "R-2", "R-1"]


def test_text_read_here_fills_only_what_had_none_and_every_text_says_where_it_came_from():
    data = dataset(row("R-1"), row("R-2"), row("R-3"), row("R-4"))
    data.loc[0, "text"] = "THE PDF'S OWN TEXT"
    read = pd.DataFrame([kept(data.loc[0, "pdf_url"], text="OCR OF A DOCUMENT THAT HAD TEXT"), kept(data.loc[1, "pdf_url"]),
                         kept(data.loc[2, "pdf_url"], text="", source="", pages=None, confidence=None, problem="not found")])
    filled = sd.add_texts(data, read)
    assert filled["text"].tolist() == ["THE PDF'S OWN TEXT", "THE TEXT", "", ""]
    assert filled["text_source"].tolist() == ["pdf", "ocr", None, None]
    assert filled.loc[1, "pages"] == 3 and filled.loc[1, "ocr_confidence"] == 88.5 and pd.isna(filled.loc[0, "pages"])
    filled["pages"] = filled["pages"].astype("float64")  # as a parquet file gives them back
    again = sd.add_texts(filled, read)  # what is published already has the three columns
    assert again["text_source"].tolist() == ["pdf", "ocr", None, None] and str(again["pages"].dtype) == "Int64"


def test_a_text_is_from_the_pdf_from_ocr_or_from_both():
    assert sd.source_of(3, 0) == "pdf" and sd.source_of(0, 2) == "ocr" and sd.source_of(4, 1) == "pdf+ocr" and sd.source_of(0, 0) == ""
