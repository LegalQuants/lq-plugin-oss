const BEGIN = "<!-- REPO-ONLY";
const END = "<!-- /REPO-ONLY -->";

export function stripRepoOnly(markdown: string) {
  let remaining = markdown;
  let output = "";

  while (remaining.length > 0) {
    const start = remaining.indexOf(BEGIN);

    if (start === -1) {
      output += remaining;
      break;
    }

    output += remaining.slice(0, start);
    const fromOpen = remaining.slice(start);
    const openEnd = fromOpen.indexOf("-->");

    if (openEnd === -1) {
      throw new Error("Unclosed REPO-ONLY opening comment in markdown");
    }

    const afterOpen = fromOpen.slice(openEnd + 3);
    const end = afterOpen.indexOf(END);

    if (end === -1) {
      throw new Error("Unclosed REPO-ONLY block in markdown");
    }

    remaining = afterOpen.slice(end + END.length).replace(/^\n/, "");
  }

  return output.replace(/^\n+/, "").replace(/\n{3,}/g, "\n\n");
}

/** Remove repository annotations before Markdown reaches a public package. */
export function preparePackagedMarkdown(markdown: string): string {
  const withoutRepoBlocks = stripRepoOnly(markdown);
  let remaining = withoutRepoBlocks;
  let output = "";

  while (remaining.length > 0) {
    const start = remaining.indexOf("<!--");
    if (start === -1) {
      output += remaining;
      break;
    }

    output += remaining.slice(0, start);
    const end = remaining.indexOf("-->", start + 4);
    if (end === -1) {
      throw new Error("Unclosed internal HTML comment in packaged markdown");
    }
    remaining = remaining.slice(end + 3);
  }

  return output
    .replace(/^\n+/, "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/\n+$/, "\n");
}
