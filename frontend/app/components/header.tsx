"use client";
import "../globals.css";
import Image from 'next/image';
import { useState, useEffect } from "react";

const Header = () => {
    const [theme, setTheme] = useState("Eclipse");
    const [isClient, setIsClient] = useState(false);

    const themes = [
        { value: "light", label: "Light" },
        { value: "Eclipse", label: "Eclipse " },
        { value: "ocean", label: "Ocean Blue" },
        { value: "forest", label: "Forest Green" },
        { value: "sunset", label: "Sunset" },
        { value: "royal", label: "Royal Purple" },
        { value: "monochrome", label: "Modern Monochrome" },
        { value: "terracotta", label: "Earthy Terracotta" },
        { value: "mint", label: "Cool Mint" },
        { value: "berry", label: "Berry" },
        { value: "midnight-gold", label: "Midnight Gold" },
        { value: "cosmic-amber", label: "Cosmic Amber" }
    ];

    useEffect(() => {
        setIsClient(true);
        const savedTheme = localStorage.getItem("theme") || "Eclipse";
        setTheme(savedTheme);
        document.documentElement.className = savedTheme;
    }, []);

    const handleThemeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
        const newTheme = e.target.value;
        setTheme(newTheme);
        localStorage.setItem("theme", newTheme);

        // Remove all theme classes first
        document.documentElement.classList.remove(...themes.map(t => t.value));
        // Add the selected theme class
        document.documentElement.classList.add(newTheme);
    };

    return (
        <header className="header">
            <div className="header-left">
                <select
                    className="input"
                    id="modelDropdown"
                    aria-label="Model Selector"
                >
                    <option value="">Select Model</option>
                    <option value="v10.h5">Super Resolved Model v10.h5</option>
                    <option value="Super_Resolved_Model-imagenet_pairs-Epochs(100).h5">
                        Super Resolved Model imagenet pairs
                    </option>
                </select>
            </div>
            <div className="header-right">
                {isClient && (
                    <select
                        className="input"
                        onChange={handleThemeChange}
                        aria-label="Theme Selector"
                        style={{ minWidth: '150px', marginRight: '10px' }}
                    // select theme as a placeholder
                    >
                    <option value="">Select Theme</option>

                        {themes.map((themeOption) => (
                            <option key={themeOption.value} value={themeOption.value}>
                                {themeOption.label}
                            </option>
                        ))}
                    </select>
                )}
                <button type="button" className="logo">
                    <p>CHAI</p>
                </button>
            </div>
        </header>
    );
};

export default Header;