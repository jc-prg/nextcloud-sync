import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    webdav_url: Mapped[str] = mapped_column(String, nullable=False)
    username: Mapped[str] = mapped_column(String, nullable=False)
    password_enc: Mapped[str] = mapped_column(String, nullable=False)
    storage_limit_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Periodic call of Nextcloud's cron.php (background jobs in "Webcron" mode)
    cron_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    cron_interval_minutes: Mapped[int] = mapped_column(Integer, default=5)
    cron_url: Mapped[str | None] = mapped_column(String, nullable=True)  # override; derived from webdav_url if empty
    cron_last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cron_last_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cron_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    source_rules: Mapped[list["SyncRule"]] = relationship(
        "SyncRule", foreign_keys="SyncRule.source_account_id", back_populates="source_account"
    )
    dest_rules: Mapped[list["SyncRule"]] = relationship(
        "SyncRule", foreign_keys="SyncRule.dest_account_id", back_populates="dest_account"
    )

    @property
    def cron_effective_url(self) -> str | None:
        """cron_url, or <server root>/cron.php derived from a Nextcloud WebDAV URL."""
        if self.cron_url:
            return self.cron_url
        idx = self.webdav_url.find("/remote.php/")
        return self.webdav_url[:idx] + "/cron.php" if idx >= 0 else None


class SyncDirection(str, enum.Enum):
    one_way = "one_way"
    two_way = "two_way"


class SyncRule(Base):
    __tablename__ = "sync_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    source_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    source_path: Mapped[str] = mapped_column(String, nullable=False)
    dest_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    dest_path: Mapped[str] = mapped_column(String, nullable=False)

    direction: Mapped[SyncDirection] = mapped_column(
        Enum(SyncDirection), default=SyncDirection.one_way, nullable=False
    )
    schedule_cron: Mapped[str] = mapped_column(String, nullable=False)
    delete_orphans: Mapped[bool] = mapped_column(Boolean, default=False)

    # Exclusion filters
    exclude_hidden: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_patterns: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of regex strings
    exclude_subfolders: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of subfolder paths relative to source_path
    exclude_folder_names: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of folder names excluded at any depth
    known_subfolders: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of all subfolder paths seen at last save
    min_file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)  # bytes
    max_file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)  # bytes

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    source_account: Mapped["Account"] = relationship(
        "Account", foreign_keys=[source_account_id], back_populates="source_rules"
    )
    dest_account: Mapped["Account"] = relationship(
        "Account", foreign_keys=[dest_account_id], back_populates="dest_rules"
    )
    jobs: Mapped[list["SyncJob"]] = relationship("SyncJob", back_populates="rule")


class JobStatus(str, enum.Enum):
    running = "running"
    success = "success"
    error = "error"
    partial = "partial"
    aborted = "aborted"


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sync_rule_id: Mapped[int] = mapped_column(ForeignKey("sync_rules.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.running)
    files_added: Mapped[int] = mapped_column(Integer, default=0)
    files_updated: Mapped[int] = mapped_column(Integer, default=0)
    files_deleted: Mapped[int] = mapped_column(Integer, default=0)
    bytes_transferred: Mapped[int] = mapped_column(Integer, default=0)

    rule: Mapped["SyncRule"] = relationship("SyncRule", back_populates="jobs")
    logs: Mapped[list["SyncLog"]] = relationship("SyncLog", back_populates="job")


class LogLevel(str, enum.Enum):
    info = "info"
    warning = "warning"
    error = "error"


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sync_job_id: Mapped[int] = mapped_column(ForeignKey("sync_jobs.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    level: Mapped[LogLevel] = mapped_column(Enum(LogLevel), default=LogLevel.info)
    message: Mapped[str] = mapped_column(Text)
    path: Mapped[str | None] = mapped_column(String, nullable=True)

    job: Mapped["SyncJob"] = relationship("SyncJob", back_populates="logs")
