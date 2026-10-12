import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { useNotificationStore } from "@/stores/notification-store";
import { NotificationToasts } from "@/components/NotificationToast";

function flushStore() {
  useNotificationStore.setState({ notifications: [], centreOpen: false });
}

// A parent that re-renders NotificationToasts on demand, mimicking the live
// mobile shell which re-renders the toast host while a toast is visible.
function Harness({ forceKey }: { forceKey?: number }) {
  return <NotificationToasts topInset="calc(44px)" key={forceKey} />;
}

describe("mobile toast auto-dismiss exploratory", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    flushStore();
  });
  afterEach(() => vi.useRealTimers());

  it("CASE A: no re-render — toast dismisses after 5s", () => {
    useNotificationStore.getState().addNotification({
      source: "system",
      level: "info",
      title: "New taOS build available",
      body: "Reload",
    });
    render(<Harness />);
    expect(screen.getByText("New taOS build available")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(5000));
    expect(screen.queryByText("New taOS build available")).not.toBeInTheDocument();
  });

  it("CASE B: parent re-renders during the timer — does the toast dismiss?", () => {
    useNotificationStore.getState().addNotification({
      source: "system",
      level: "info",
      title: "New taOS build available",
      body: "Reload",
    });
    const { rerender } = render(<Harness />);
    expect(screen.getByText("New taOS build available")).toBeInTheDocument();
    // Simulate the shell re-rendering the toast host partway through the 5s.
    act(() => vi.advanceTimersByTime(2000));
    rerender(<Harness />);
    act(() => vi.advanceTimersByTime(5000));
    const gone = screen.queryByText("New taOS build available");
    expect(gone).not.toBeInTheDocument();
  });

  it("CASE C: repeated parent re-renders every 1s — toast persists?", () => {
    useNotificationStore.getState().addNotification({
      source: "system",
      level: "info",
      title: "New taOS build available",
      body: "Reload",
    });
    const { rerender } = render(<Harness />);
    expect(screen.getByText("New taOS build available")).toBeInTheDocument();
    // Simulate frequent shell re-renders (scroll/store ticks) every 1s.
    for (let i = 0; i < 10; i++) {
      act(() => vi.advanceTimersByTime(1000));
      rerender(<Harness />);
    }
    const gone = screen.queryByText("New taOS build available");
    expect(gone).not.toBeInTheDocument();
  });
});
