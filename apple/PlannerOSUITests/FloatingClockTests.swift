#if os(macOS)
import XCTest
import AppKit

@MainActor
final class FloatingClockTests: PlannerScreenTests {
    private func launchClock(frame: String? = nil) {
        app = XCUIApplication()
        app.launchEnvironment["PLANNER_UI_TEST_SERVER"] = server.base
        app.launchEnvironment["PLANNER_UI_TEST_KEY"] = server.key
        app.launchEnvironment["PLANNER_UI_TEST_CLOCK"] = "1"
        if let frame { app.launchEnvironment["PLANNER_UI_TEST_CLOCK_FRAME"] = frame }
        app.launchArguments = ["-ApplePersistenceIgnoreState", "YES"]
        app.launch()
        XCTAssertTrue(tile.waitForExistence(timeout: 15))
        XCTAssertTrue(clock.waitForExistence(timeout: 5), app.debugDescription)
    }

    private var clock: XCUIElement {
        app.descendants(matching: .any).matching(identifier: "floating-clock").firstMatch
    }
    private var shrink: XCUIElement { clock.buttons["Make the clock small"] }
    private var expand: XCUIElement { clock.buttons["Show the full clock"] }

    func testClockRecoversAnOffscreenFrameWithoutChangingCompactPreference() {
        launchClock(frame: "{{10000, 10000}, {268, 40}}")
        let beganSmall = expand.exists
        let top = NSScreen.screens.first?.frame.maxY ?? 0
        eventually("the clock is wholly on a connected display") {
            let frame = self.clock.frame
            return NSScreen.screens.contains { screen in
                let area = screen.visibleFrame
                let visible = CGRect(x: area.minX, y: top - area.maxY, width: area.width, height: area.height)
                return visible.insetBy(dx: -2, dy: -2).contains(frame)
            }
        }
        app.terminate()
        launchClock()
        XCTAssertEqual(expand.exists, beganSmall, "recovery changed the compact preference")
    }

    func testClockShrinksAndExpandsWithoutLosingItsPosition() {
        launchClock()
        let beganSmall = expand.exists
        if !beganSmall {
            // A restored frame may only partly intersect a changed display.
            // The first resize deliberately brings it fully on screen.
            activate(shrink)
            XCTAssertTrue(expand.waitForExistence(timeout: 3))
        }
        activate(expand)
        XCTAssertTrue(shrink.waitForExistence(timeout: 3))
        let full = clock.frame
        activate(shrink)
        XCTAssertTrue(expand.waitForExistence(timeout: 3))
        eventually("clock is the compact pill") { self.clock.frame.width < 300 && self.clock.frame.height < 60 }
        XCTAssertEqual(clock.frame.maxX, full.maxX, accuracy: 2)
        XCTAssertEqual(clock.frame.minY, full.minY, accuracy: 2)
        XCTAssertTrue(clock.staticTexts.matching(NSPredicate(format: "label == 'Vacant' OR value == 'Vacant'")).firstMatch.exists)
        activate(expand)
        XCTAssertTrue(shrink.waitForExistence(timeout: 3))
        eventually("full clock is restored") { abs(self.clock.frame.width - full.width) < 2 && abs(self.clock.frame.height - full.height) < 2 }
        if beganSmall { activate(shrink) }
    }

    func testDraggingFromTheClockTickDoesNotCompleteTheTask() throws {
        let format = DateFormatter()
        format.locale = Locale(identifier: "en_US_POSIX")
        format.timeZone = TimeZone(identifier: "Asia/Kolkata")
        format.dateFormat = "HH:mm"
        let id = try server.create("Clock drag fixture", date: today, time: format.string(from: Date()), minutes: 60)
        launchClock()
        let beganSmall = expand.exists
        if !beganSmall { activate(shrink) }
        XCTAssertTrue(expand.waitForExistence(timeout: 3))
        let tick = clock.buttons["Complete Clock drag fixture from the clock"]
        XCTAssertTrue(tick.waitForExistence(timeout: 5))
        let original = clock.frame
        let from = tick.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        from.click(forDuration: 0.1, thenDragTo: from.withOffset(CGVector(dx: -60, dy: 60)))
        eventually("panel moved from its tick") { abs(self.clock.frame.minX - original.minX) > 10 || abs(self.clock.frame.minY - original.minY) > 10 }
        XCTAssertEqual(try server.task(id, on: today)?["done"] as? Bool, false)
        let moved = clock.frame
        let back = tick.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        back.click(forDuration: 0.1, thenDragTo: back.withOffset(CGVector(dx: original.minX - moved.minX, dy: original.minY - moved.minY)))
        if !beganSmall { activate(expand) }
    }
}
#endif
