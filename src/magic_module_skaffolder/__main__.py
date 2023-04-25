import os
import logging
from magic_module_skaffolder.main import main

if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),format="%(levelname)s: %(message)s")
    main()