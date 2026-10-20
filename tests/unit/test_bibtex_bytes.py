from dataclasses import replace

from acquire_research_papers.bibliography import decode_bibtex_bytes
from acquire_research_papers.delivery import GenericDelivery


def test_delivery_preserves_bom_crlf_and_non_utf8_bytes(tmp_path, verified_pair):
    for index, encoding in enumerate(("utf-8-sig", "gb18030")):
        text = verified_pair.bibtex_text.replace("@article", "% 中文注释\r\n@article") + "\r\n"
        raw = text.encode(encoding)
        pair = replace(verified_pair, bibtex_text=decode_bibtex_bytes(raw)[0], bibtex_bytes=raw)
        delivered = GenericDelivery(tmp_path / str(index)).deliver(pair=pair, paper_id="byte-test")
        assert delivered.bibtex.read_bytes() == raw
        assert GenericDelivery(tmp_path / str(index)).deliver(
            pair=pair, paper_id="byte-test") == delivered


def test_decoder_reports_encoding_without_changing_original_payload():
    raw = "@article{k,title={论文}}\r\n".encode("gb18030")
    text, encoding = decode_bibtex_bytes(raw)
    assert encoding == "gb18030"
    assert text.encode(encoding) == raw
