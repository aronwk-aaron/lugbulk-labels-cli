import bricklink


def write(path, text):
    path.write_bytes(text.replace("\n", "\r\n").encode())  # BrickLink files are CRLF


PARTS = """Category ID\tCategory Name\tNumber\tName\tAlternate Item Number\tWeight (in Grams)


5\tBrick\t3004\tBrick 1 x 2\t3004f1,93792\t0.83
26\tPlate\t3811\tBaseplate 32 x 32\t\t107
28\tAnimal\tx223\tFrog\t\t?
"""
CODES = """Item No\tColor\tCode
3004\tLight Bluish Gray\t4211388
3811\tBright Green\t6097276
x223\tBlack\t6584302
"""


def test_load_catalog_by_header_not_name(tmp_path):
    write(tmp_path / "downloaded-1.txt", PARTS)
    write(tmp_path / "whatever.txt", CODES)
    catalog = bricklink.load(str(tmp_path))
    assert catalog["4211388"] == bricklink.PartInfo("3004", "Light Bluish Gray", 0.83)
    assert catalog["6097276"].weight == 107
    assert catalog["6584302"] == bricklink.PartInfo("x223", "Black", None)  # "?" weight


def test_missing_files_mean_no_catalog(tmp_path):
    assert bricklink.load(str(tmp_path / "nope")) == {}
    write(tmp_path / "Parts.txt", PARTS)  # codes file missing
    assert bricklink.load(str(tmp_path)) == {}
