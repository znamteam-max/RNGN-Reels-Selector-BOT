import unittest

from reels_bot.parser import ParseError, normalize_url, parse_idea


class ParserTests(unittest.TestCase):
    def test_parses_valid_message(self):
        idea = parse_idea(
            "МК | Майкл Джексон выполняет трюки без страховки | 9 | "
            "https://www.instagram.com/reel/ABC123/?igsh=test"
        )
        self.assertEqual(idea.category.code, "МК")
        self.assertEqual(idea.rating, 9)
        self.assertEqual(
            idea.normalized_url,
            "https://instagram.com/reel/ABC123",
        )

    def test_instagram_tracking_does_not_change_identity(self):
        first = normalize_url("https://instagram.com/reel/ABC123/?igsh=one")
        second = normalize_url("https://www.instagram.com/reel/ABC123/?igsh=two")
        self.assertEqual(first, second)

    def test_youtube_video_id_is_preserved(self):
        first = normalize_url("https://youtube.com/watch?v=AAA&utm_source=x")
        second = normalize_url("https://www.youtube.com/watch?v=BBB&utm_source=x")
        self.assertNotEqual(first, second)

    def test_rating_range_is_checked(self):
        with self.assertRaises(ParseError):
            parse_idea("СК | История | 11 | https://example.com/item")

    def test_unconnected_category_explains_problem(self):
        with self.assertRaisesRegex(ParseError, "пока не подключена"):
            parse_idea("НХЛ | История | 8 | https://example.com/item")


if __name__ == "__main__":
    unittest.main()
