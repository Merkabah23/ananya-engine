from engine import render


def test_renders_carousel_slide_at_canvas_size(tmp_path):
    img = render.render_slide([
        "Every Indian home has one room nobody is allowed to sit in.",
        "It has the best sofa in the house. The cushions nobody leans on. A TV remote with the plastic still on it. ₹1,20,000 of furniture, for guests.",
        "Swipe to read →",
    ])
    assert img.size == (1080, 1350)


def test_overflowing_slide_is_split():
    long_para = "word " * 120
    slides = render.split_for_fit([{"paragraphs": [long_para, long_para, long_para]}])
    assert len(slides) >= 2


def test_carousel_is_cover_reading_slides_and_end_card(tmp_path, monkeypatch):
    from engine import config
    monkeypatch.setattr(config, "OUT", tmp_path)
    draft = {"cover": {"headline": "Mummy's old gold is now the jeweller's [supply line.]", "sub": "s",
                       "proof": {"figure": "6% → 15%", "label": "customs duty on gold"}},
             "slides": [{"paragraphs": ["hook", "Swipe to read →"]},
                        {"paragraphs": ["A reading slide with **one bold line.**"], "big": {"figure": "46%", "label": "l"},
                         "source": "Source: x"},
                        {"paragraphs": ["The payoff."]}],
             "end": {"save": "Take the two numbers to the counter on 6 Nov.", "send": "Send it on."}}
    paths = render.render_post({"id": "x", "format": "carousel", "draft": draft})
    assert len(paths) == 4  # cover + two reading slides + end card
    near = lambda a, b: all(abs(x - y) <= 6 for x, y in zip(a, b))  # JPEG shifts colours slightly
    teal = [near(render.Image.open(p).getpixel((5, 5)), render.TEAL) for p in paths]
    assert teal == [False, False, False, True]


def test_cover_headline_stays_inside_the_grid_crop():
    img = render.render_cover({"headline": "An unusually long cover headline that must shrink to [stay inside]"}, 5)
    strip = [img.getpixel((x, 400)) for x in list(range(0, render.SAFE - 40)) + list(range(render.W - render.SAFE + 40, render.W))]
    assert all(px == render.PAPER for px in strip)
