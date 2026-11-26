import datetime
from typing import Dict, List, Optional, Tuple
import uuid

from streaming.dao import RatingDAO, StatsDAO, TitleDAO, UserDAO, ViewDAO
from streaming.models import Title, User


class CatalogService:
    def __init__(self, titles: TitleDAO, stats: StatsDAO):
        self.titles = titles
        self.stats = stats

    def title_details(self, title_id: uuid.UUID) -> Optional[dict]:
        title = self.titles.get(title_id)
        if not title:
            return None
        views, sum_ratings, count_ratings = self.stats.get(title_id)
        avg = (sum_ratings / count_ratings) if count_ratings > 0 else None
        return {
            "title": title,
            "views": views,
            "average_rating": avg,
            "rating_count": count_ratings,
        }

    def titles_of_genre(self, genre: str, limit: int = 20) -> List[dict]:
        return self.titles.list_by_genre(genre, limit=limit)


class TrendingService:
    def __init__(self, views: ViewDAO, titles: TitleDAO):
        self.views = views
        self.titles = titles

    def top10(self, day: datetime.date) -> List[dict]:
        daily_views = self.views.views_of_day(day)
        sorted_views = sorted(daily_views.items(), key=lambda item: (-item[1], item[0]))[:10]
        result = []
        for title_id, view_count in sorted_views:
            t = self.titles.get(title_id)
            if t:
                result.append({"title": t, "views": view_count})
        return result


class ReviewService:
    def __init__(self, users: UserDAO, titles: TitleDAO, ratings: RatingDAO):
        self.users = users
        self.titles = titles
        self.ratings = ratings

    def rate(self, user_id: uuid.UUID, title_id: uuid.UUID, rating: int, comment: Optional[str] = None):
        user = self.users.get(user_id)
        if not user:
            raise LookupError(f"Utilisateur {user_id} introuvable")
        title = self.titles.get(title_id)
        if not title:
            raise LookupError(f"Titre {title_id} introuvable")
        self.ratings.add(
            user_id=user_id,
            title_id=title_id,
            rating=rating,
            comment=comment,
            username=user.username,
            title=title.title,
        )
