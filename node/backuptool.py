import tarfile
import time
import os
import json


class BackupTool(object):
    """Simple backup utility."""

    def __init__(self):
        pass

    @staticmethod
    def backup(openbazaar_installation_path,
               backup_folder_path,
               on_success_callback=None,
               on_error_callback=None):
        """
        Creates an 'openbazaar-YYYY-MM-DD-hh-mm-ss.tar.gz' file
        inside the html/backups/ folder.

        @param openbazaar_installation_path: str
            The path to OpenBazaar's installation folder,
            where the db/ folder lives.

        @param backup_folder_path: str
            The folder where the backup file will reside.

        Optional callback functions can be passed:
        @param on_success_callback(backupFilePath: str)
        @param on_error_callback(errorMessage: str)
        """

        date_time = time.strftime('%Y-%h-%d-%H-%M-%S')
        output_file_path = os.path.join(
            backup_folder_path,
            "openbazaar-%s.tar.gz" % date_time
        )

        # Create the folder for the backup, if it doesn't exist.
        try:
            os.makedirs(backup_folder_path)
        except os.error:
            pass

        db_folder = os.path.join(openbazaar_installation_path, "db")
        try:
            with tarfile.open(output_file_path, "w:gz") as tar:
                tar.add(db_folder, arcname=os.path.basename(db_folder))
        except tarfile.TarError as exc:
            # TODO: Install proper error logging.
            print "Error while backing up to:", output_file_path
            if on_error_callback is not None:
                on_error_callback(exc)
            return

        if on_success_callback is not None:
            on_success_callback(output_file_path)

    @staticmethod
    def restore(backup_tar_filepath):
        raise NotImplementedError

    @staticmethod
    def get_installation_path():
        """Return the Project Root path."""
        file_abs_path = os.path.abspath(__file__)
        real_file_abs_path = os.path.realpath(file_abs_path)
        return real_file_abs_path[:real_file_abs_path.find('/node')]

    @classmethod
    def get_backup_path(cls):
        """Return the backup path."""
        # TODO: Make backup path configurable on server settings.
        return os.path.join(
            cls.get_installation_path(), 'html', 'backups'
        )


class Backup(json.JSONEncoder):
    """
    A (meant to be immutable) POPO to represent a backup.
    So that we can tell our Web client about the backups available.
    """
    def __init__(self,
                 file_name=None,
                 full_file_path=None,
                 created_timestamp_millis=None,
                 size_in_bytes=None):
        super(Backup, self).__init__()
        self.file_name = file_name
        self.full_file_path = full_file_path
        self.created_timestamp_millis = created_timestamp_millis
        self.size_in_bytes = size_in_bytes

    def to_dict(self):
        """Return a dictionary with attributes of self."""
        return {
            "file_name": self.file_name,
            "full_file_path": self.full_file_path,
            "created_timestamp_millis": self.created_timestamp_millis,
            "size_in_bytes": self.size_in_bytes
        }

    def __repr__(self):
        return repr(self.to_dict())

    @classmethod
    def get_backups(cls, backup_folder_path=None):
        """
        Return a list of Backup objects found in the backup folder path given.
        """
        if backup_folder_path is None or not os.path.isdir(backup_folder_path):
            return []

        result_gen = (
            cls.get_backup(os.path.join(backup_folder_path, x))
            for x in os.listdir(backup_folder_path)
        )

        result = [backup for backup in result_gen if backup is not None]
        result.reverse()
        return result

    @classmethod
    def get_backup(cls, backup_file_path):
        """
        Create and return a Backup object from a backup path.
        Return None if the path was invalid.
        """
        try:
            file_stat = os.stat(backup_file_path)
            file_name = os.path.basename(backup_file_path)
        except os.error:
            print "Invalid backup path:", backup_file_path
            return None

        created_timestamp_millis = file_stat.st_ctime
        size_in_bytes = file_stat.st_size

        return cls(
            file_name=file_name,
            full_file_path=backup_file_path,
            created_timestamp_millis=created_timestamp_millis,
            size_in_bytes=size_in_bytes
        )


class BackupJSONEncoder(json.JSONEncoder):
    # pylint: disable=method-hidden
    def default(self, o):
        if isinstance(o, Backup):
            return o.to_dict()
