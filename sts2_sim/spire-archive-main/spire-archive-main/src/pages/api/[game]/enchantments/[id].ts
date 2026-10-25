import type { APIRoute } from 'astro';
import { getData } from '../../../../lib/data';
import { getGame, getLocale, jsonResponse, notFoundResponse } from '../../_util';

export const GET: APIRoute = async ({ params, url }) => {
  const game = getGame(params);
  if (!game) return notFoundResponse();
  if (game === 'sts1') return jsonResponse({ error: 'enchantments are not available for sts1' }, { status: 404 });

  const id = String(params.id ?? '');
  const locale = getLocale(url);
  const { enchantmentById } = await getData(game, locale);
  const enchantment = enchantmentById.get(id);
  if (!enchantment) {
    return jsonResponse({ error: 'not found' }, { status: 404 });
  }
  return jsonResponse(enchantment);
};
