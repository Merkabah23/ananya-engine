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
    slides = render.split_for_fit([[long_para, long_para, long_para]])
    assert len(slides) >= 2
