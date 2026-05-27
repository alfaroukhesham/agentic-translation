# WordPress page ACF translation

Translate human-readable strings inside an ACF field tree for one page.

**Preserve unchanged:**
- URLs (`http://`, `https://`, relative paths used as links)
- Attachment/media IDs (`_attachment_id`, `logo`, `icon`, numeric IDs)
- HTML tags and attributes (translate visible text inside tags only)
- Repeater row count and key order (mirror English structure exactly)

**Translate:**
- Headlines, labels, button text, descriptions, and other user-visible strings

Output valid JSON only: one object `{"acf_fields": { ... }}` with the same keys/nesting as the input.
