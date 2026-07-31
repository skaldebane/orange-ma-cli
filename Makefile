PREFIX ?= $(HOME)/.local
DATA_DIR = $(PREFIX)/share/orange
BIN_DIR = $(PREFIX)/bin

install:
	mkdir -p $(BIN_DIR)
	install -Dm 755 orange_ma.py $(DATA_DIR)/orange.py
	ln -sf $(abspath $(DATA_DIR)/orange.py) $(BIN_DIR)/orange

uninstall:
	rm -f $(BIN_DIR)/orange
	rm -rf $(DATA_DIR)

.PHONY: install uninstall
