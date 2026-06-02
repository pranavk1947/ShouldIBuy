export interface ExampleChip {
  label: string;
  url: string;
}

// TODO(M1): point these at real fixture listings served by the backend.
export const EXAMPLES: ExampleChip[] = [
  {
    label: "iPhone 13 Pro",
    url: "https://example.com/listings/iphone-13-pro-128gb",
  },
  {
    label: "Sony A7 III",
    url: "https://example.com/listings/sony-a7-iii-body",
  },
  {
    label: "Herman Miller Aeron",
    url: "https://example.com/listings/herman-miller-aeron-size-b",
  },
  {
    label: "PS5 Disc Edition",
    url: "https://example.com/listings/ps5-disc-edition",
  },
];
