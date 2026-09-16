.PHONY: help test install-global agy zcode claude

PLUGIN_NAME := sdlc-skills
# Agent name -> install destination (set in install-global)
AGENTS := agy zcode claude

help: ## Display this help screen
	@echo "Available Makefile targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

test: ## Run the SessionStart hook test suite
	sh tests/test_check_metaproject.sh

install-global: ## Install the plugin globally for an agent: make install-global [agy|zcode|claude]
	@agent="$(strip $(filter $(AGENTS),$(MAKECMDGOALS)))"; \
	case "$$agent" in \
	  agy) \
	    dest="$${HOME}/.gemini/config/plugins/$(PLUGIN_NAME)";; \
	  zcode) \
	    dest="$${HOME}/.zcode/plugins/$(PLUGIN_NAME)";; \
	  claude) \
	    dest="$${HOME}/.claude/plugins/cache/$(PLUGIN_NAME)/$(PLUGIN_NAME)/1.0.0";; \
	  *) \
	    echo "usage: make install-global [agy|zcode|claude]" >&2; exit 1;; \
	esac; \
	echo "Installing $(PLUGIN_NAME) -> $$dest"; \
	mkdir -p "$$dest"; \
	rsync -a --delete \
	  --exclude '.git/' \
	  --exclude '.DS_Store' \
	  --exclude '.remember/' \
	  --exclude '.serena/' \
	  ./ "$$dest/"; \
	echo "Done."

# Swallow the agent argument so make doesn't look for a rule named e.g. "agy"
agy zcode claude:
	@:
