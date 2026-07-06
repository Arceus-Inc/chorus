export type Product = {
  id: string;
  name: string;
  description: string;
  priceCents: number;
};

export const PRODUCTS: Product[] = [
  {
    id: 'p1',
    name: 'Arc Mug',
    description: 'Stoneware mug, 12oz. Dishwasher safe.',
    priceCents: 1599,
  },
  {
    id: 'p2',
    name: 'Chorus Tee',
    description: 'Unisex cotton tee. True to size.',
    priceCents: 2499,
  },
  {
    id: 'p3',
    name: 'Field Notebook',
    description: 'Dot grid, 80 pages, soft cover.',
    priceCents: 899,
  },
];

export function getProductById(id: string): Product | undefined {
  return PRODUCTS.find((p) => p.id === id);
}
