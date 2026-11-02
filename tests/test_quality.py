from app.plex.quality import extract_quality, representative_episode, title_quality
from tests.fakes import FakeItem, audio, media, video


def movie(*medias):
    return FakeItem(lite={"media": list(medias)})


def test_4k_dv_atmos():
    item = movie(media("4k", streams=[video(DOVIPresent=True, colorTrc="smpte2084"),
                                      audio("English (TrueHD Atmos 7.1)")]))
    assert extract_quality(item) == ["4K", "DV", "ATMOS"]


def test_hdr10_without_dv():
    item = movie(media("2160", streams=[video(colorTrc="smpte2084")]))
    assert extract_quality(item) == ["4K", "HDR10"]


def test_1080_and_unknown_resolution():
    assert extract_quality(movie(media("1080", streams=[video()]))) == ["1080P"]
    assert extract_quality(movie(media("720", streams=[video()]))) == []
    assert extract_quality(movie(media("1080p", streams=[video()]))) == ["1080P"]


def test_best_version_wins():
    item = movie(media("720", streams=[video()]), media("4k", streams=[video()]), media("1080", streams=[video()]))
    assert extract_quality(item) == ["4K"]


def test_dtsx_variants():
    for title in ("DTS:X 7.1", "DTS-X", "English (DTSX)"):
        assert "DTSX" in extract_quality(movie(media("1080", streams=[video(), audio(title)])))
    assert "DTSX" not in extract_quality(movie(media("1080", streams=[video(), audio("DTS-HD MA 5.1")])))


def test_remux_glued_and_from_release_name():
    item = movie(media("1080", file="/m/Movie.1999.BDRemux.mkv", streams=[video()]))
    assert "REMUX" in extract_quality(item)
    renamed = movie(media("4k", file="/m/Movie (1999).mkv",
                          streams=[video(extended="Movie.1999.2160p.UHD.BluRay.REMUX.HDR.HEVC")]))
    assert "REMUX" in extract_quality(renamed)


def test_webdl():
    for file in ("Show.S01E01.1080p.WEB-DL.mkv", "x.WEBDL.mkv", "x_WEB.DL_y.mkv", "x web dl.mkv"):
        assert "WEBDL" in extract_quality(movie(media("1080", file=file, streams=[video()])))
    assert "WEBDL" not in extract_quality(movie(media("1080", file="x.WEBRip.mkv", streams=[video()])))
    assert "WEBDL" not in extract_quality(movie(media("1080", file="cobweb.dlx.mkv", streams=[video()])))


def test_streams_loaded_after_reload():
    lite = media("4k", streams=[])
    full = media("4k", streams=[video(DOVIPresent=True)])
    item = FakeItem(lite={"media": [lite]}, full={"media": [full]})
    assert extract_quality(item) == ["4K", "DV"]
    assert item.reloads == 1


def test_no_media():
    assert extract_quality(FakeItem()) == []


def episode(season, index, resolution="1080"):
    item = FakeItem(TYPE="episode", lite={"media": [media(resolution, streams=[video()])]})
    item.seasonNumber, item.index = season, index
    return item


def test_representative_episode_without_season_one():
    target = episode(3, 2)
    show = FakeItem(TYPE="show", episodes=[episode(5, 1), target, episode(3, 4), episode(0, 1)])
    assert representative_episode(show) is target


def test_representative_episode_prefers_s01e01():
    target = episode(1, 1, "4k")
    show = FakeItem(TYPE="show", episodes=[episode(0, 1), episode(2, 1), target, episode(1, 2)])
    assert representative_episode(show) is target
    assert title_quality(show) == ["4K"]


def test_representative_episode_fallback_skips_specials():
    target = episode(2, 3)
    show = FakeItem(TYPE="show", episodes=[episode(0, 1), episode(3, 1), target, episode(2, 5)])
    assert representative_episode(show) is target


def test_show_without_regular_episodes():
    assert title_quality(FakeItem(TYPE="show", episodes=[episode(0, 1)])) == []
