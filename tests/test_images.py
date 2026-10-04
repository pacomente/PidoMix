"""Compresión de imágenes con Cloudinary."""
from app.services.images import cdn, upload_transformation

URL = "https://res.cloudinary.com/q1tovzqq/image/upload/v1790466142/pidomix/products/zmdveaiqpzyqvdxdfk9e.png"


def test_cdn_pide_tamano_y_formato_liviano():
    assert cdn(URL, "product") == "https://res.cloudinary.com/q1tovzqq/image/upload/f_auto,q_auto,c_limit,w_720/v1790466142/pidomix/products/zmdveaiqpzyqvdxdfk9e.png"
    assert "w_256/" in cdn(URL, "logo") and "w_300/" in cdn(URL, 300)
    assert cdn(cdn(URL, "logo"), "cover") == cdn(URL, "logo")  # no se transforma dos veces


def test_cdn_deja_igual_lo_que_no_es_cloudinary():
    assert cdn(None) is None and cdn("") == ""
    assert cdn("https://ejemplo.com/foto.jpg") == "https://ejemplo.com/foto.jpg"
    assert cdn("/static/icons/trappi.svg") == "/static/icons/trappi.svg"


def test_al_subir_se_achica_segun_el_uso():
    assert upload_transformation("pidomix/stores/logos") == [{"width": 512, "height": 512, "crop": "limit", "quality": "auto:good"}]
    assert upload_transformation("pidomix/products")[0]["width"] == 1600
    assert upload_transformation("otra/carpeta")[0]["width"] == 1600
