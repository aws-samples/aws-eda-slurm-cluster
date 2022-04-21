
help:
	@echo "Usage: make [ help | clean ]"

clean:
	git clean -d -f -x
	# -d: Recurse into directories
