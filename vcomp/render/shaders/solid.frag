#version 330

uniform vec4 u_color;   // straight RGBA
out vec4 f_color;

void main() {
    f_color = u_color;
}
