"""WebSocket and SSE streaming endpoints hardened for free-host behavior."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from starlette.responses import StreamingResponse

from backend.api.dependencies import get_price_feed
from backend.services.price_feed import PriceFeed, PriceTick


router = APIRouter(tags=["streaming"])
logger = logging.getLogger(__name__)
HEARTBEAT_INTERVAL = 20


def _tick_dict(tick: PriceTick) -> dict:
    return {
        "symbol": tick.symbol,
        "timestamp": tick.timestamp.isoformat(),
        "price": tick.price,
        "volume": tick.volume,
        "bid": tick.bid,
        "ask": tick.ask,
        "open": tick.open,
        "high": tick.high,
        "low": tick.low,
        "close": tick.close,
        "prev_close": tick.prev_close,
        "change": tick.change,
        "change_pct": tick.change_pct,
        "feed_mode": tick.feed_mode,
    }


async def _send_status(websocket: WebSocket, feed: PriceFeed) -> None:
    await websocket.send_json({"type": "status", **feed.feed_status})


@router.get("/stream/feed-status")
async def feed_status(feed: PriceFeed = Depends(get_price_feed)):
    return feed.feed_status


@router.get("/stream/symbols")
async def available_symbols(feed: PriceFeed = Depends(get_price_feed)):
    return {"symbols": feed.available_symbols()}


@router.get("/stream/watchlist")
async def watchlist_snapshot(
    symbols: str = Query(default="", description="Comma-separated symbols"),
    feed: PriceFeed = Depends(get_price_feed),
):
    symbol_list = [symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()] or None
    return {"mode": feed.feed_mode, "data": feed.get_watchlist_snapshot(symbol_list)}


@router.get("/stream/market-overview")
async def market_overview(feed: PriceFeed = Depends(get_price_feed)):
    return feed.get_market_overview()


@router.get("/stream/categories")
async def categories(feed: PriceFeed = Depends(get_price_feed)):
    return {
        "watchlist": [{"symbol": symbol, "available": symbol in feed.available_symbols()} for symbol in feed.default_watchlist()]
    }


@router.post("/stream/connect-live")
async def connect_live(
    symbols: str = Query(default="", description="Comma-separated symbols"),
    feed: PriceFeed = Depends(get_price_feed),
):
    symbol_list = [symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()] or None
    return feed.connect_live(symbol_list)


@router.post("/stream/disconnect-live")
async def disconnect_live(feed: PriceFeed = Depends(get_price_feed)):
    return feed.disconnect_live()


@router.get("/stream/last_close/{symbol}")
async def last_close(symbol: str, feed: PriceFeed = Depends(get_price_feed)):
    tick = feed.get_latest_price(symbol)
    if tick is None:
        raise HTTPException(status_code=404, detail=f"No price data for {symbol}")
    return _tick_dict(tick)


@router.websocket("/stream/price/{symbol}")
async def price_websocket(websocket: WebSocket, symbol: str):
    feed = get_price_feed()
    await websocket.accept()
    heartbeat = asyncio.create_task(_heartbeat(websocket))
    try:
        await _send_status(websocket, feed)
        async for tick in feed.stream(symbol, speed=10.0, recent_days=10):
            await websocket.send_json({"type": "tick", **_tick_dict(tick)})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("Single-symbol websocket failed: %s", exc)
        with suppress(Exception):
            await websocket.send_json({"type": "status", **feed.feed_status})
    finally:
        heartbeat.cancel()


@router.get("/stream/price/{symbol}")
async def price_sse(symbol: str, feed: PriceFeed = Depends(get_price_feed)):
    async def event_generator():
        yield f"data: {json.dumps({'type': 'status', **feed.feed_status})}\n\n"
        try:
            async for tick in feed.stream(symbol, speed=10.0, recent_days=10):
                yield f"data: {json.dumps({'type': 'tick', **_tick_dict(tick)})}\n\n"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Single-symbol SSE failed: %s", exc)
            yield f"data: {json.dumps({'type': 'status', **feed.feed_status})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.websocket("/stream/multi")
async def multi_price_websocket(websocket: WebSocket):
    feed = get_price_feed()
    await websocket.accept()
    heartbeat = asyncio.create_task(_heartbeat(websocket))
    stream_task: asyncio.Task | None = None
    try:
        await _send_status(websocket, feed)
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            action = message.get("action")
            if action == "subscribe":
                symbols = [symbol.upper() for symbol in message.get("symbols", []) if symbol]
                if stream_task:
                    stream_task.cancel()
                stream_task = asyncio.create_task(_multi_stream_loop(websocket, feed, symbols))
            elif action == "unsubscribe" and stream_task:
                stream_task.cancel()
                stream_task = None
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat.cancel()
        if stream_task:
            stream_task.cancel()


@router.get("/stream/multi")
async def multi_price_sse(
    symbols: str = Query(description="Comma-separated symbols"),
    feed: PriceFeed = Depends(get_price_feed),
):
    symbol_list = [symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="Provide at least one symbol")

    async def event_generator():
        yield f"data: {json.dumps({'type': 'status', **feed.feed_status})}\n\n"
        try:
            async for tick in feed.stream_multi(symbol_list, speed=12.0, recent_days=10):
                yield f"data: {json.dumps({'type': 'tick', **_tick_dict(tick)})}\n\n"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Multi SSE failed: %s", exc)
            yield f"data: {json.dumps({'type': 'status', **feed.feed_status})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def _multi_stream_loop(websocket: WebSocket, feed: PriceFeed, symbols: list[str]) -> None:
    try:
        await websocket.send_json({"type": "status", **feed.feed_status})
        async for tick in feed.stream_multi(symbols, speed=12.0, recent_days=10):
            await websocket.send_json({"type": "tick", **_tick_dict(tick)})
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Multi-stream websocket failed: %s", exc)
        with suppress(Exception):
            await websocket.send_json({"type": "status", **feed.feed_status})


async def _heartbeat(websocket: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await websocket.send_json({"type": "ping"})
    except (asyncio.CancelledError, WebSocketDisconnect):
        return
