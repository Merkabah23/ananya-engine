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


def test_cover_bracket_next_to_punctuation_closes_the_teal():
    # "[goodbye]," used to leave the "]" on the slide and the rest of the line teal
    img = render.render_cover({"headline": "'Let's catch up soon' is a [goodbye], not a plan", "sub": ""}, 5)
    assert img.size == (render.W, render.H)


def test_long_save_line_is_not_cut(monkeypatch):
    drawn = []
    real = render.ImageDraw.ImageDraw.text
    monkeypatch.setattr(render.ImageDraw.ImageDraw, "text", lambda self, xy, t, *a, **k: (drawn.append(t), real(self, xy, t, *a, **k))[1])
    save = "Pull this up before the next offsite speech that makes a weekend call feel compulsory, again and again."
    render.render_end({"save": save, "send": "x"}, 5)
    assert "compulsory," in " ".join(drawn) and "again." in " ".join(drawn)


def test_reel_holds_each_screen_for_its_words(tmp_path, monkeypatch):
    from engine import config, reel
    monkeypatch.setattr(config, "OUT", tmp_path)
    draft = {"cover": {"headline": "Every Indian home keeps its [best room] for guests", "sub": "s"},
             "slides": [{"paragraphs": ["hook", "Swipe to read →"]},
                        {"paragraphs": ["The best furniture and the best light are kept for relatives who visit twice a year."]},
                        {"paragraphs": ["**The drawing room moved into our phones.**"]}],
             "end": {"save": "Before you post the next one.", "send": "The cousin with the perfect grid."}}
    post = {"id": "r", "format": "carousel", "draft": draft}
    paths = render.render_post(post)
    assert reel.holds(post["alt_texts"], len(paths)) == [2.0, 5.0, 2.75, 4.0]
    assert reel.hold(60) == 5.5 and reel.hold(0) == 2.0
    framed = reel.frame(paths[1], tmp_path / "f.jpg")
    assert render.Image.open(framed).size == (1080, 1920)
    video, secs = reel.build(paths, post["alt_texts"], tmp_path / "reel.mp4")
    assert video.stat().st_size > 10_000 and secs == round(2.0 + 5.0 + 2.75 + 4.0 + reel.FADE, 2)


def test_buffer_sends_a_reel_with_the_cover_as_thumbnail(monkeypatch):
    from engine import buffer, config
    monkeypatch.setattr(config, "DRY_RUN", True)
    post = {"due": "2026-11-10T20:30:00+05:30", "draft": {"caption": "c"}, "video_url": "https://v/reel.mp4"}
    body = buffer.build_input(post, ["https://i/slide_01.jpg", "https://i/slide_02.jpg"])
    assert body["assets"] == [{"video": {"url": "https://v/reel.mp4", "thumbnailUrl": "https://i/slide_01.jpg"}}]
    assert body["metadata"]["instagram"]["type"] == "reel"
