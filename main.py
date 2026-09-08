# This text describes the purpose of this Python file.
"""Entry point of the MultiRoofs LoD 2.2 CityJSON generator."""


# Makes Python type annotations behave in a more flexible/modern way.
from __future__ import annotations


# Imports the sys module, which gives access to Python/system-related functions.
import sys

# Imports traceback, which helps create detailed error information.
import traceback

# Imports TracebackType, which is used below as a type hint for error traceback information.
from types import TracebackType


# Imports QApplication creates the GUI application, which represents the whole PyQt GUI application.
# Imports QMessageBox, which is used to show popup message boxes to the user.
from PyQt6.QtWidgets import QApplication, QMessageBox


# Imports the MainWindow class from the file UI/MainWindow.py.
# This is the main GUI window of the application.
from UI.MainWindow import MainWindow



# Defines a function called install_exception_hook.
# -> None means this function does not return a value.
def install_exception_hook() -> None:

    # This documentation explains what the function is used for.
    # It catches unexpected Python errors and shows them to the GUI user.
    """Show unexpected errors instead of closing the window silently.

    Without this, an exception raised inside a Qt slot is printed to a
    console the user usually does not see.
    """


    # Defines another function called hook inside install_exception_hook.
    # This function will receive information about unexpected Python errors.
    def hook(

        # exc_type contains the TYPE of error that occurred.
        # Example: FileNotFoundError, ValueError, TypeError, etc.
        exc_type: type[BaseException],

        # exc_value contains the actual error object and its message.
        exc_value: BaseException,

        # exc_traceback contains information about WHERE the error happened.
        # "| None" means this value may also be empty.
        exc_traceback: TracebackType | None,

    # This function also does not return a value.
    ) -> None:

        # Creates one large text string containing the complete Python error traceback.
        text = "".join(

            # Formats the error type, error message, and traceback into readable text.
            traceback.format_exception(exc_type, exc_value, exc_traceback)
        )


        # Prints the full error information to Python's standard error output.
        # If the program was started from a terminal, this error can appear there.
        print(text, file=sys.stderr)


        # Checks whether a QApplication object currently exists.
        # In other words: checks whether the GUI application has been created.
        if QApplication.instance() is not None:

            # Shows a critical/error popup message to the user.
            QMessageBox.critical(

                # None means this error popup does not need a specific parent window.
                None,

                # This is the title shown at the top of the popup window.
                "Unexpected error",

                # This is the message shown inside the popup.
                # \n means new line.
                # {exc_value} inserts the actual Python error message.
                f"An unexpected error occurred:\n\n{exc_value}",
            )


    # Replaces Python's normal uncaught-error handler with our custom hook function.
    # After this, unexpected errors will go through hook().
    sys.excepthook = hook



# Defines the main function of the program.
# This function creates and starts the GUI application.
def main() -> None:

    # Creates the QApplication object.
    # QApplication manages the whole Qt GUI application.
    # sys.argv passes any command-line arguments to Qt.
    app = QApplication(sys.argv)


    # Gives the application an organization name.
    # QSettings can use this information when saving settings.
    app.setOrganizationName("Multiroof")

    # Gives this specific application a name.
    # QSettings also uses this to identify where the application's settings belong.
    app.setApplicationName("CityJSONGenerator")


    # Calls the function defined above.
    # This activates our custom unexpected-error handler.
    install_exception_hook()


    # Creates an object from the MainWindow class.
    # This causes MainWindow.__init__() in MainWindow.py to run.
    # The main GUI is created here. creates your main window,
    window = MainWindow()

    # Makes the main GUI window visible on the screen.
    window.show()


    # app.exec() starts Qt's event loop.
    # The event loop keeps the application running and listens for things like:
    # button clicks, mouse events, keyboard events, QProcess output, and window closing.
    #
    # sys.exit() then returns Qt's final exit code to the operating system
    # when the application closes.keeps the GUI running and listening for user actions.
    sys.exit(app.exec())



# Checks whether this Python file is being run directly.
# If we run: python main.py
# then __name__ will equal "__main__".
if __name__ == "__main__":

    # Calls the main() function and therefore starts the entire application.
    main()