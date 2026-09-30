"""Built-in sample labels, for trying out a label design without a sheet
(--sample; the web app's live preview uses the same set). Chosen to show
the awkward cases: a clear part, a white part, a huge part, a long name,
and a color with no swatch."""

import config
from ordering import order_records
from records import LabelRecord

_PARTS = [
    # element, description, LEGO color, BrickLink color, [(person, qty)]
    ("6097276", "BASE PLATE 32X32", "Bright Green", "Bright Green", [("Ann Lee", "4"), ("Bob Roe", "10")]),
    ("6508677", "BRICK 2X4, TRANSPARENT", "Transparent", "Trans-Clear", [("Cat Diaz", "100")]),
    ("6545156", "PLANT, W/ PLATE 1X1, NO. 1", "White", "White", [("Alexandria Montgomery-Smith", "250")]),
    ("4211388", "BRICK 1X2", "Medium Stone Grey", "Light Bluish Gray", [("Ann Lee", "25"), ("Bob Roe", "50"), ("Dan Wu", "500")]),
    ("6584302", "FROG", "Black", "Black", [("Eve Park", "50")]),
    ("6514224", "FLAT TILE 1X2", "Transparent Light Blue", "Trans-Light Blue", [("Bob Roe", "75")]),
]


def sample_records() -> list[LabelRecord]:
    records = [
        LabelRecord(person=person, element_id=eid, description=desc, lego_color=lego,
                    bl_color=bl, qty=qty, image_url=config.IMAGE_URL_TEMPLATE.format(element_id=eid))
        for eid, desc, lego, bl, orders in _PARTS for person, qty in orders
    ]
    return order_records(records)
