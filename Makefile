
help:
	@echo "Usage: make [ help | clean ]"

test:
	pytest -x -v tests

jekyll:
	gem install jekyll bundler
	bundler install
	bundle exec jekyll serve

clean:
	git clean -d -f -x
	# -d: Recurse into directories
