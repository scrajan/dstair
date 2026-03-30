from extensions import db
from typing import TypeVar, Type, Optional, List, Any

T = TypeVar("T", bound="ActiveRecordMixin")

class ActiveRecordMixin:
    """
    Mixin to provide Active Record pattern methods directly on SQLAlchemy models.
    Replaces the need for a separate repository layer.
    """

    @classmethod
    def get_by_id(cls: Type[T], id_value: Any) -> Optional[T]:
        """Fetch a record by its primary key using the session's optimized get method."""
        return db.session.get(cls, id_value)

    @classmethod
    def get_by_id_locked(cls: Type[T], id_value: Any) -> Optional[T]:
        """
        Fetch by primary key with FOR UPDATE lock.
        Dynamically resolves the PK column name to support models like User.
        """
        pk_column = cls.__mapper__.primary_key[0]
        return db.session.query(cls).with_for_update().filter(pk_column == id_value).first()

    @classmethod
    def get_all(cls: Type[T]) -> List[T]:
        return db.session.query(cls).all()

    @classmethod
    def filter_by(cls: Type[T], **kwargs) -> List[T]:
        return db.session.query(cls).filter_by(**kwargs).all()

    @classmethod
    def find_one(cls: Type[T], **kwargs) -> Optional[T]:
        """Find the first record matching the given criteria."""
        return db.session.query(cls).filter_by(**kwargs).first()

    @classmethod
    def count(cls: Type[T]) -> int:
        """Return the total count of records for this model."""
        return db.session.query(cls).count()

    def save(self: T, commit: bool = True) -> T:
        """Add the instance to the session and optionally commit."""
        db.session.add(self)
        if commit:
            self._commit()
        return self

    def update(self: T, commit: bool = True) -> T:
        """Persist changes to the database."""
        if commit:
            self._commit()
        return self

    def delete(self, commit: bool = True) -> None:
        """Remove the instance from the database."""
        db.session.delete(self)
        if commit:
            self._commit()

    @staticmethod
    def _commit() -> None:
        """Internal helper to safely commit or rollback on failure."""
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e
