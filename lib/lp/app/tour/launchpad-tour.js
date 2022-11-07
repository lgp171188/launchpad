// JavaScript Document

var dropDown = null;

var dropDownTimeOut = 0;

function dropDownIn() {
    clearTimeout(dropDownTimeOut);
    dropDown.classList.add("menu");
}

function dropDownOut() {
    dropDownTimeOut = setTimeout(function() {
        dropDown.classList.remove("menu");
    }, 400);
}

function initDropDown() {
    dropDown = document.getElementById("navigation-drop-down");
    dropDown.addEventListener("mouseover", dropDownIn);
    dropDown.addEventListener("mouseout", dropDownOut);
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initDropDown);
} else {
    initDropDown();
}
