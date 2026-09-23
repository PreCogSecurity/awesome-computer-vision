# Contributing to Awesome Computer Vision

Thanks for taking the time to contribute! This is a curated list of computer
vision resources, and every addition makes it more useful for the community.

## How to add a link

1. Fork the repository.
2. Add your link to the appropriate section in `README.md` (or `people.md`
   for the academic genealogy list).
3. Follow the existing entry format:

   ```markdown
   * [Resource Name](https://example.com/) - Short description - Author (Affiliation) Year
   ```

   * Use `*` for list items.
   * Keep entries in a single line.
   * Prefer the canonical project page over a paper PDF or a mirror.
   * Add a short description after the link so readers know what to expect.
4. Run `npx markdownlint-cli2 README.md people.md CONTRIBUTING.md` locally
   (requires [Node.js](https://nodejs.org/)) and fix any reported issues.
5. Commit with a descriptive message, e.g. `Add link to FooBar library`.
6. Open a pull request.

## Guidelines

* **Relevance**: only computer vision resources (books, courses, papers,
  software, datasets, tutorials, blogs, and related material).
* **Quality**: prefer resources that are actively maintained, widely used, or
  historically significant to the field.
* **No duplicates**: check the section before adding a link; if a resource is
  already listed, suggest an update instead of a second entry.
* **No broken links**: verify the URL works before submitting. If you find a
  dead link, open a pull request that removes or replaces it.
* **Keep it tidy**: one entry per bullet, alphabetical or topical ordering
  within a section, and no trailing whitespace.

## Reporting issues

If a link is broken, a resource is mislabeled, or a section is missing
something important, open an issue or send a pull request. Please include the
URL and, for broken links, the date you noticed the problem.

## Code of conduct

Be respectful and constructive. This project is maintained by volunteers and
welcomes contributions from everyone, regardless of experience level.
