"""Package DAO – accès Cassandra.

Exporte les cinq classes DAO pour une importation simple :

    from streaming.dao import TitleDAO, UserDAO, RatingDAO, ViewDAO, StatsDAO
"""

from .titles import TitleDAO
from .users import UserDAO
from .ratings import RatingDAO
from .views import ViewDAO
from .stats import StatsDAO
